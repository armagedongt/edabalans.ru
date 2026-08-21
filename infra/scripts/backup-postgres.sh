#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly PROJECT_DIR="/opt/edabalans"
readonly S3_ENV_FILE="/root/.config/edabalans/s3.env"
readonly BACKUP_DIR="/var/backups/edabalans"
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

install -d -m 700 "${BACKUP_DIR}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
created_files=()

cleanup() {
    if ((${#created_files[@]} > 0)); then
        rm -f -- "${created_files[@]}"
    fi
}
trap cleanup EXIT

cd "${PROJECT_DIR}"

for database in "${DATABASES[@]}"; do
    backup_name="${database}-${timestamp}.dump"
    backup_path="${BACKUP_DIR}/${backup_name}"
    checksum_path="${backup_path}.sha256"
    created_files+=("${backup_path}" "${checksum_path}")

    docker compose exec -T postgres \
        pg_dump --username "${POSTGRES_USER}" --dbname "${database}" --format custom \
        > "${backup_path}"

    test -s "${backup_path}"
    (
        cd "${BACKUP_DIR}"
        sha256sum "${backup_name}" > "${backup_name}.sha256"
    )

    for file in "${backup_path}" "${checksum_path}"; do
        docker run --rm \
            -e AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION \
            -v "${BACKUP_DIR}:/backup:ro" \
            amazon/aws-cli:latest \
            --endpoint-url "${S3_ENDPOINT}" \
            s3 cp "/backup/$(basename "${file}")" \
            "s3://${BACKUP_BUCKET}/postgres/$(basename "${file}")" \
            --only-show-errors
    done

    echo "Backup uploaded: s3://${BACKUP_BUCKET}/postgres/${backup_name}"
done
