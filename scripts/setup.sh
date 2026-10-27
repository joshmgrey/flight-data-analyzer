#!/usr/bin/env bash
# Provision Flight Data Analyzer on Ubuntu 22.04+ (EC2 or WSL2). Safe to re-run.
#
#   scripts/setup.sh               install everything and start the 5-minute timer
#   scripts/setup.sh --no-systemd  skip the timer (use deploy/cron/fda-ingest.cron instead)
#
# Steps: apt packages -> PostgreSQL role/database -> Python venv -> /etc/fda/fda.env
#        -> schema -> systemd units. Run as your normal user; it calls sudo where needed.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
DB_NAME="${FDA_DB_NAME:-flightdata}"
DB_USER="${FDA_DB_USER:-fda}"
ENV_DIR=/etc/fda
ENV_FILE="$ENV_DIR/fda.env"
INSTALL_SYSTEMD=true

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-systemd) INSTALL_SYSTEMD=false ;;
        -h|--help)    usage; exit 0 ;;
        *)            usage; die "unknown option: $1" ;;
    esac
    shift
done

preflight() {
    [[ $EUID -ne 0 ]] || die "run as your normal user, not root (sudo is used where needed)"
    # shellcheck source=/dev/null
    [[ -r /etc/os-release ]] && . /etc/os-release
    [[ "${ID:-}" == "ubuntu" ]] || warn "tested on Ubuntu; detected '${ID:-unknown}'"

    if [[ "$APP_DIR" == /mnt/* ]]; then
        warn "repo is on the Windows filesystem ($APP_DIR); clone it under ~ for speed and Unix permissions"
    fi

    if $INSTALL_SYSTEMD && [[ "$(ps -p 1 -o comm=)" != "systemd" ]]; then
        if grep -qi microsoft /proc/version 2>/dev/null; then
            die "systemd is not running in this WSL distro. Add this to /etc/wsl.conf:
    [boot]
    systemd=true
then run 'wsl --shutdown' from Windows, reopen Ubuntu and re-run this script.
(Or use --no-systemd and the cron entry in deploy/cron/.)"
        fi
        die "systemd is not PID 1; re-run with --no-systemd"
    fi
}

install_packages() {
    local pkgs=(postgresql postgresql-contrib python3-venv python3-pip curl jq)
    local missing=()
    for p in "${pkgs[@]}"; do
        dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        log "apt packages already installed"
        return
    fi
    log "installing: ${missing[*]}"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
}

start_postgres() {
    if [[ "$(ps -p 1 -o comm=)" == "systemd" ]]; then
        sudo systemctl enable --now postgresql >/dev/null
    else
        sudo service postgresql start >/dev/null
    fi
    for _ in {1..20}; do
        pg_isready -q && return
        sleep 1
    done
    die "PostgreSQL did not become ready"
}

# cd / so psql does not complain that the postgres user cannot read our working directory.
psql_admin() { (cd / && sudo -u postgres psql -v ON_ERROR_STOP=1 -tAq "$@"); }

# Prints the new password if the role was created, nothing if it already existed.
create_database() {
    if [[ "$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'")" == "1" ]]; then
        log "database role '$DB_USER' already exists"
    else
        local password
        password="$(openssl rand -hex 24)"
        psql_admin -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$password'"
        log "created database role '$DB_USER'"
        NEW_DB_PASSWORD="$password"
    fi
    if [[ "$(psql_admin -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")" != "1" ]]; then
        psql_admin -c "CREATE DATABASE $DB_NAME OWNER $DB_USER"
        log "created database '$DB_NAME'"
    fi
}

setup_venv() {
    if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
        log "creating virtualenv"
        python3 -m venv "$APP_DIR/.venv"
    fi
    log "installing Python package"
    "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
    "$APP_DIR/.venv/bin/pip" install -q -e "${APP_DIR}[dev]"
}

write_env_file() {
    sudo install -d -m 755 "$ENV_DIR"
    if sudo test -f "$ENV_FILE"; then
        log "$ENV_FILE exists; leaving it alone"
        if [[ -n "${NEW_DB_PASSWORD:-}" ]]; then
            warn "role '$DB_USER' was just created; update DATABASE_URL in $ENV_FILE with password: $NEW_DB_PASSWORD"
        fi
    else
        [[ -n "${NEW_DB_PASSWORD:-}" ]] \
            || die "$ENV_FILE is missing but role '$DB_USER' already exists; create it from deploy/fda.env.example"
        log "writing $ENV_FILE (mode 600, owner $APP_USER)"
        sed "s|postgresql://fda:CHANGE_ME@localhost:5432/flightdata|postgresql://$DB_USER:$NEW_DB_PASSWORD@localhost:5432/$DB_NAME|" \
            "$APP_DIR/deploy/fda.env.example" | sudo tee "$ENV_FILE" >/dev/null
    fi
    sudo chown "$APP_USER:$APP_USER" "$ENV_FILE"
    sudo chmod 600 "$ENV_FILE"
}

apply_schema() {
    log "applying database schema"
    # shellcheck source=/dev/null
    (set -a; . "$ENV_FILE"; set +a; "$APP_DIR/.venv/bin/python" -m fda.db init)
}

install_units() {
    log "installing systemd units"
    local unit
    for unit in fda-ingest.service fda-ingest.timer; do
        sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER@|$APP_USER|g" \
            "$APP_DIR/deploy/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
    done
    sudo systemctl daemon-reload
    sudo systemctl enable --now fda-ingest.timer
    systemctl list-timers fda-ingest.timer --no-pager
}

main() {
    preflight
    install_packages
    start_postgres
    create_database
    setup_venv
    write_env_file
    apply_schema
    if $INSTALL_SYSTEMD; then
        install_units
    else
        log "skipping systemd; see deploy/cron/fda-ingest.cron"
    fi
    log "done. Next: scripts/healthcheck.sh in ~10 minutes, scripts/inspect_logs.sh any time"
}

main
