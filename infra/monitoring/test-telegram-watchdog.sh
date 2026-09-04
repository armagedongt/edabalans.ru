#!/usr/bin/env bash
set -Eeuo pipefail

test_dir="$(mktemp -d)"
cleanup() {
    [[ "${test_dir}" == /tmp/* ]] && rm -rf -- "${test_dir}"
}
trap cleanup EXIT

mkdir -p "${test_dir}/app"
fake_docker="${test_dir}/docker"
cat >"${fake_docker}" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${FAKE_DOCKER_LOG}"
if [[ "$*" == "compose ps -q telegram-bot" ]]; then
    printf '%s' "${FAKE_CONTAINER_ID:-}"
elif [[ "$1" == "inspect" ]]; then
    printf '%s' "${FAKE_HEALTH:-healthy}"
fi
EOF
chmod +x "${fake_docker}"

run_watchdog() {
    EDABALANS_WATCHDOG_APP_DIR="${test_dir}/app" \
    EDABALANS_WATCHDOG_LOCK_FILE="${test_dir}/deploy.lock" \
    EDABALANS_WATCHDOG_RESTART_MARKER="${test_dir}/restart.marker" \
    EDABALANS_WATCHDOG_DOCKER_BIN="${fake_docker}" \
    FAKE_DOCKER_LOG="${test_dir}/docker.log" \
    FAKE_CONTAINER_ID="${FAKE_CONTAINER_ID:-}" \
    FAKE_HEALTH="${FAKE_HEALTH:-healthy}" \
        bash "$(dirname "$0")/edabalans-telegram-watchdog"
}

: >"${test_dir}/docker.log"
FAKE_CONTAINER_ID=container-1 FAKE_HEALTH=healthy run_watchdog
! grep -qE 'restart|compose up' "${test_dir}/docker.log"

: >"${test_dir}/docker.log"
FAKE_CONTAINER_ID= run_watchdog
grep -q 'compose up -d --no-deps telegram-bot' "${test_dir}/docker.log"

: >"${test_dir}/docker.log"
rm -f "${test_dir}/restart.marker"
FAKE_CONTAINER_ID=container-1 FAKE_HEALTH=unhealthy run_watchdog
grep -q 'compose restart telegram-bot' "${test_dir}/docker.log"
[[ -s "${test_dir}/restart.marker" ]]

: >"${test_dir}/docker.log"
FAKE_CONTAINER_ID=container-1 FAKE_HEALTH=unhealthy run_watchdog
! grep -q 'compose restart telegram-bot' "${test_dir}/docker.log"

: >"${test_dir}/docker.log"
printf '1\n' >"${test_dir}/restart.marker"
FAKE_CONTAINER_ID=container-1 FAKE_HEALTH=unhealthy run_watchdog
grep -q 'compose restart telegram-bot' "${test_dir}/docker.log"

: >"${test_dir}/docker.log"
flock "${test_dir}/deploy.lock" sleep 5 &
lock_pid=$!
for _ in {1..50}; do
    if ! flock --nonblock "${test_dir}/deploy.lock" true; then
        break
    fi
    sleep 0.01
done
FAKE_CONTAINER_ID= run_watchdog
! grep -q 'compose up' "${test_dir}/docker.log"
kill "${lock_pid}" 2>/dev/null || true
wait "${lock_pid}" 2>/dev/null || true

echo "Local Telegram watchdog tests passed"
