#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly PROJECT_DIR="/opt/edabalans"
readonly S3_ENV_FILE="/root/.config/edabalans/s3.env"
readonly RESTORE_DIR="/var/backups/edabalans/restore-test"
readonly BACKUP_BUCKET="edabalans-postgres-backups-ajessi9majsb7glatojn"
readonly DATABASES=("edabalans" "nocodb_meta")

set -a
# shellcheck disable=SC1091
source "${PROJECT_DIR}/.env"
# shellcheck disable=SC1091
source "${S3_ENV_FILE}"
set +a

export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY}"
export AWS_DEFAULT_REGION="${S3_REGION}"

install -d -m 700 "${RESTORE_DIR}"

cleanup() {
    cd "${PROJECT_DIR}"
    for database in "${DATABASES[@]}"; do
        docker compose exec -T postgres dropdb \
            --username "${POSTGRES_USER}" --if-exists --force "${database}_restore_test" \
            >/dev/null 2>&1 || true
    done
    find "${RESTORE_DIR}" -mindepth 1 -maxdepth 1 -type f -delete
    rmdir "${RESTORE_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

for database in "${DATABASES[@]}"; do
    latest_key="$(
        docker run --rm \
            -e AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION \
            amazon/aws-cli:latest \
            --endpoint-url "${S3_ENDPOINT}" \
            s3api list-objects-v2 \
            --bucket "${BACKUP_BUCKET}" \
            --prefix "postgres/${database}-" \
            --query "sort_by(Contents[?ends_with(Key, '.dump')], &LastModified)[-1].Key" \
            --output text
    )"

    if [[ -z "${latest_key}" || "${latest_key}" == "None" ]]; then
        echo "No ${database} dump found in S3" >&2
        exit 1
    fi

    restore_path="${RESTORE_DIR}/$(basename "${latest_key}")"
    checksum_key="${latest_key}.sha256"

    for key in "${latest_key}" "${checksum_key}"; do
        docker run --rm \
            -e AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION \
            -v "${RESTORE_DIR}:/restore" \
            amazon/aws-cli:latest \
            --endpoint-url "${S3_ENDPOINT}" \
            s3 cp "s3://${BACKUP_BUCKET}/${key}" "/restore/$(basename "${key}")" \
            --only-show-errors
    done

    test -s "${restore_path}"
    (
        cd "${RESTORE_DIR}"
        sha256sum --check "$(basename "${checksum_key}")"
    )

    restore_database="${database}_restore_test"
    cd "${PROJECT_DIR}"
    docker compose exec -T postgres dropdb \
        --username "${POSTGRES_USER}" --if-exists --force "${restore_database}"
    docker compose exec -T postgres createdb \
        --username "${POSTGRES_USER}" "${restore_database}"
    docker compose exec -T postgres pg_restore \
        --username "${POSTGRES_USER}" --dbname "${restore_database}" --exit-on-error \
        < "${restore_path}"

    restored_tables="$(
        docker compose exec -T postgres psql \
            --username "${POSTGRES_USER}" --dbname "${restore_database}" \
            --tuples-only --no-align \
            --command "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';"
    )"

    if [[ ! "${restored_tables}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Restore verification failed for ${database}: no public tables" >&2
        exit 1
    fi

    echo "Restore test passed: ${database}, ${restored_tables} public tables"
done
