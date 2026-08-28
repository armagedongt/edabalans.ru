#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly S3_ENV_FILE="/root/.config/edabalans/s3.env"
readonly BACKUP_DIR="${AUTHOR_MEMORY_BACKUP_DIR:-/var/backups/edabalans/author-memory/incoming}"
readonly BACKUP_BUCKET="edabalans-postgres-backups-ajessi9majsb7glatojn"
readonly BACKUP_PREFIX="author-memory"

test -d "${BACKUP_DIR}"
mapfile -t archives < <(
    find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'author-memory-*.aes256' -printf '%f\n' | sort
)

if ((${#archives[@]} != 1)); then
    echo "Expected exactly one encrypted author-memory archive in ${BACKUP_DIR}" >&2
    exit 1
fi

readonly archive="${archives[0]}"
artifacts=("${archive}" "${archive}.json" "${archive}.sha256")
for artifact in "${artifacts[@]}"; do
    if [[ ! -f "${BACKUP_DIR}/${artifact}" ]]; then
        echo "Incomplete author-memory backup set: missing ${artifact}" >&2
        exit 1
    fi
done

mapfile -t unexpected < <(
    find "${BACKUP_DIR}" -maxdepth 1 -type f \
        ! -name "${archive}" ! -name "${archive}.json" ! -name "${archive}.sha256" \
        -printf '%f\n' | sort
)
if ((${#unexpected[@]} != 0)); then
    echo "Unexpected files in author-memory incoming directory: ${unexpected[*]}" >&2
    exit 1
fi

(
    cd "${BACKUP_DIR}"
    sha256sum --check "${archive}.sha256"
)
readonly archive_sha="$(sha256sum "${BACKUP_DIR}/${archive}" | cut -d' ' -f1)"
readonly metadata_archive="$(
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["archive"])' \
        "${BACKUP_DIR}/${archive}.json"
)"
readonly metadata_sha="$(
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["sha256"])' \
        "${BACKUP_DIR}/${archive}.json"
)"
if [[ "${metadata_archive}" != "${archive}" || "${metadata_sha}" != "${archive_sha}" ]]; then
    echo "Author-memory metadata does not match ${archive}" >&2
    exit 1
fi

source "${S3_ENV_FILE}"

export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY}"
export AWS_DEFAULT_REGION="${S3_REGION}"

for artifact in "${artifacts[@]}"; do
    docker run --rm \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_DEFAULT_REGION \
        -v "${BACKUP_DIR}:/backup:ro" \
        amazon/aws-cli:latest \
        --endpoint-url "${S3_ENDPOINT}" \
        s3 cp "/backup/${artifact}" \
        "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/${artifact}" \
        --only-show-errors

    remote_size="$(
        docker run --rm \
            -e AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION \
            amazon/aws-cli:latest \
            --endpoint-url "${S3_ENDPOINT}" \
            s3api head-object \
            --bucket "${BACKUP_BUCKET}" \
            --key "${BACKUP_PREFIX}/${artifact}" \
            --query ContentLength \
            --output text
    )"
    local_size="$(stat -c '%s' "${BACKUP_DIR}/${artifact}")"
    if [[ "${remote_size}" != "${local_size}" ]]; then
        echo "Uploaded size mismatch for ${artifact}" >&2
        exit 1
    fi
    local_sha="$(sha256sum "${BACKUP_DIR}/${artifact}" | cut -d' ' -f1)"
    remote_sha="$(
        docker run --rm \
            -e AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION \
            amazon/aws-cli:latest \
            --endpoint-url "${S3_ENDPOINT}" \
            s3 cp "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/${artifact}" - \
            --only-show-errors \
        | sha256sum | cut -d' ' -f1
    )"
    if [[ "${remote_sha}" != "${local_sha}" ]]; then
        echo "Uploaded checksum mismatch for ${artifact}" >&2
        exit 1
    fi
    echo "Verified: s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/${artifact}"
done
