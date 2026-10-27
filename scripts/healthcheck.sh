#!/usr/bin/env bash
# Health check for the ingest pipeline (REQ-042). Prints PASS/WARN/FAIL per check.
#
#   scripts/healthcheck.sh [--max-age-min N] [--no-systemd] [--quiet]
#
# Exit status: 0 if no check failed, 1 otherwise, so it can drive cron mail or monitoring.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${FDA_ENV_FILE:-/etc/fda/fda.env}"
MAX_AGE_MIN=15
USE_SYSTEMD=true
QUIET=false
DISK_WARN_PCT=80
DISK_FAIL_PCT=90

FAILS=0
WARNS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-age-min) MAX_AGE_MIN="${2:?--max-age-min needs a value}"; shift ;;
        --no-systemd)  USE_SYSTEMD=false ;;
        --quiet)       QUIET=true ;;
        -h|--help)     sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

report() {  # report LEVEL NAME MESSAGE
    local level=$1 name=$2 msg=$3 color
    case "$level" in
        PASS) color=32 ;;
        WARN) color=33; WARNS=$((WARNS + 1)) ;;
        FAIL) color=31; FAILS=$((FAILS + 1)) ;;
    esac
    if ! $QUIET || [[ "$level" != PASS ]]; then
        printf '\033[%sm%-4s\033[0m  %-16s %s\n' "$color" "$level" "$name" "$msg"
    fi
}

check_timer() {
    if systemctl is-active --quiet fda-ingest.timer; then
        local next
        next="$(systemctl show fda-ingest.timer -p NextElapseUSecRealtime --value)"
        report PASS timer "active; next run ${next:-unknown}"
    else
        report FAIL timer "fda-ingest.timer is not active (sudo systemctl enable --now fda-ingest.timer)"
    fi
}

check_last_run() {
    local result status
    result="$(systemctl show fda-ingest.service -p Result --value)"
    status="$(systemctl show fda-ingest.service -p ExecMainStatus --value)"
    case "$status" in
        0) report PASS last-run "result=$result exit=0" ;;
        2) report WARN last-run "exit=2 (rate limited by OpenSky)" ;;
        3) report WARN last-run "exit=3 (OpenSky unreachable or bad response)" ;;
        *) report FAIL last-run "result=$result exit=$status (journalctl -u fda-ingest -n 50)" ;;
    esac
}

check_postgres() {
    if pg_isready -q; then
        report PASS postgres "accepting connections"
    else
        report FAIL postgres "pg_isready failed (sudo systemctl status postgresql)"
    fi
}

check_freshness() {
    if [[ ! -r "$ENV_FILE" ]]; then
        report FAIL freshness "cannot read $ENV_FILE"
        return
    fi
    local out rc
    # shellcheck source=/dev/null
    out="$(set -a; . "$ENV_FILE"; set +a; "$APP_DIR/.venv/bin/python" -m fda.health --max-age-min "$MAX_AGE_MIN" 2>&1)"
    rc=$?
    case $rc in
        0) report PASS freshness "$out" ;;
        1) report FAIL freshness "no ok poll in ${MAX_AGE_MIN} min: $out" ;;
        *) report FAIL freshness "$out" ;;
    esac
}

check_disk() {
    local dir=/var/lib/postgresql pct
    [[ -d $dir ]] || dir=/
    pct="$(df --output=pcent "$dir" | tail -1 | tr -dc '0-9')"
    if (( pct >= DISK_FAIL_PCT )); then
        report FAIL disk "${pct}% used on $dir"
    elif (( pct >= DISK_WARN_PCT )); then
        report WARN disk "${pct}% used on $dir"
    else
        report PASS disk "${pct}% used on $dir"
    fi
}

check_network() {
    # The site root costs no API credits, unlike a real /states/all call. Any HTTP
    # answer (even a 403 from its bot filter) proves DNS, routing and TLS work.
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://opensky-network.org/ || true)"
    if [[ "$code" =~ ^[1-5][0-9][0-9]$ ]]; then
        report PASS opensky "reachable (HTTP $code)"
    else
        report WARN opensky "not reachable (HTTP ${code:-none}); polls will record upstream_error"
    fi
}

if $USE_SYSTEMD; then
    check_timer
    check_last_run
fi
check_postgres
check_freshness
check_disk
check_network

$QUIET || printf '\n%d failed, %d warnings\n' "$FAILS" "$WARNS"
[[ $FAILS -eq 0 ]]
