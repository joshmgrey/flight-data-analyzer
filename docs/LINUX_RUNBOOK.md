# Linux Runbook

Hands-on deployment on Ubuntu (WSL2 on Windows, or an EC2 instance). Do each step yourself
and **type the commands rather than pasting them**. Part A does by hand what
`scripts/setup.sh` automates, so you know what the script does before you rely on it.
Record evidence for the RVTM demonstrations (D-1 to D-5) in `docs/evidence/` as you go.

Checklist for your own records:

- [ ] A. Host prepared (WSL2 systemd or EC2)
- [ ] B. Manual install of PostgreSQL, role, database
- [ ] C. Repo cloned, venv, first manual poll
- [ ] D. `setup.sh` run, timer active (D-1)
- [ ] E. Health check, log inspection, failure drills (D-2, D-3, D-4)
- [ ] F. Second `setup.sh` run (D-5)
- [ ] G. Your own Bash script (exercise)

## A. Prepare the host

### Option 1: WSL2 (already installed on this laptop: distro "Ubuntu")

In PowerShell: `wsl -d Ubuntu`. Then, inside Ubuntu:

```bash
lsb_release -a                 # confirm Ubuntu 22.04 or 24.04
ps -p 1 -o comm=               # "systemd" means systemd is running
```

If it does not print `systemd`, enable it:

```bash
sudo nano /etc/wsl.conf
# add:
# [boot]
# systemd=true
```

Then in PowerShell run `wsl --shutdown`, reopen Ubuntu and re-check `ps -p 1 -o comm=`.

WSL caveat (risk R-04): the distro may stop when no Windows terminal keeps it alive, and the
laptop sleeps. Data collected on WSL will have gaps; the coverage-gap report measures them.
For a clean multi-day run use Option 2.

### Option 2: EC2

A `t4g.small` or `t3.small` with Ubuntu 24.04, 10 GB gp3, security group allowing SSH from
your IP only. Stop it when the collection is done.

```bash
ssh -i ~/.ssh/your-key.pem ubuntu@<public-ip>
sudo apt-get update && sudo apt-get -y upgrade
timedatectl                    # "System clock synchronized: yes" (risk R-11)
```

## B. PostgreSQL by hand

```bash
sudo apt-get install -y postgresql postgresql-contrib
systemctl status postgresql    # active (exited) is normal for the wrapper unit
pg_lsclusters                  # shows version, port 5432, data directory
sudo -u postgres psql -c "SELECT version();"
```

Create the role and database. Generate a password and keep it for step D:

```bash
openssl rand -hex 24
sudo -u postgres psql
```

```sql
CREATE ROLE fda LOGIN PASSWORD '<the password>';
CREATE DATABASE flightdata OWNER fda;
\l
\q
```

Test a TCP login as the new role (this is how the app connects):

```bash
psql "postgresql://fda:<the password>@localhost:5432/flightdata" -c '\conninfo'
```

Things to look at while you are here: `sudo ls /etc/postgresql/*/main/`,
`sudo less /etc/postgresql/*/main/pg_hba.conf` (why does the TCP login use
`scram-sha-256`?), `sudo journalctl -u postgresql@*-main -n 20`.

## C. Clone, venv, one manual poll

Clone into your Linux home directory, not `/mnt/c/...` (slow, and Windows permissions
break `chmod 600`):

```bash
sudo apt-get install -y python3-venv git
cd ~
git clone https://github.com/joshmgrey/flight-data-analyzer.git
cd flight-data-analyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create the environment file with tight permissions:

```bash
sudo install -d -m 755 /etc/fda
sudo cp deploy/fda.env.example /etc/fda/fda.env
sudo chown "$USER:$USER" /etc/fda/fda.env
chmod 600 /etc/fda/fda.env
nano /etc/fda/fda.env           # put your password in DATABASE_URL
ls -l /etc/fda/fda.env          # expect -rw-------
```

Load it into your shell, create the tables and run one poll:

```bash
set -a; source /etc/fda/fda.env; set +a
python -m fda.db init
python -m fda.ingest; echo "exit code: $?"
python -m fda.ingest; echo "exit code: $?"   # should skip: rate guard
psql "$DATABASE_URL" -c "SELECT id, status, n_states, credits_remaining FROM poll_runs;"
psql "$DATABASE_URL" -c "SELECT icao24, callsign, round(baro_altitude_m) alt_m, flight_phase, dq_flags FROM state_vectors ORDER BY id DESC LIMIT 10;"
```

Run the tests on Linux against a separate test database:

```bash
sudo -u postgres psql -c "CREATE DATABASE fda_test OWNER fda;"
TEST_DATABASE_URL="postgresql://fda:<the password>@localhost:5432/fda_test" pytest -q
```

## D. Install the timer (D-1)

Read `scripts/setup.sh` top to bottom first. It will find your role and env file already
in place and skip those steps.

```bash
bash scripts/setup.sh
systemctl list-timers fda-ingest.timer
systemctl cat fda-ingest.service          # the installed unit, with your paths filled in
```

Wait 15 minutes, then:

```bash
journalctl -u fda-ingest -n 10 --no-pager
systemctl status fda-ingest.service --no-pager
```

Save that output to `docs/evidence/D-1.txt` with `ls -l /etc/fda/fda.env` and
`systemctl list-timers fda-ingest.timer`.

## E. Operate it (D-2, D-3, D-4)

```bash
scripts/healthcheck.sh; echo "exit: $?"
scripts/inspect_logs.sh --since "6 hours ago"
journalctl -u fda-ingest --since today | grep -c 'status=ok'
```

Failure drills, one at a time, re-running `scripts/healthcheck.sh` after each:

```bash
sudo systemctl stop fda-ingest.timer      # wait 16 min → FAIL timer, FAIL freshness
sudo systemctl start fda-ingest.timer     # next poll catches up (D-2)
sudo systemctl stop postgresql            # → FAIL postgres; next poll exits 4
journalctl -u fda-ingest -n 3 --no-pager  # see status=db_error and the exit code
sudo systemctl start postgresql
```

## F. Idempotency (D-5)

```bash
sha256sum /etc/fda/fda.env
psql "$DATABASE_URL" -tAc "SELECT count(*) FROM state_vectors"
bash scripts/setup.sh
sha256sum /etc/fda/fda.env                # unchanged
psql "$DATABASE_URL" -tAc "SELECT count(*) FROM state_vectors"   # unchanged or higher
```

## G. Exercise: write one script yourself

Write `scripts/backup_db.sh` without copying from anywhere, then run it from cron or a
second systemd timer:

- `set -euo pipefail`, a `--dir` option (default `~/fda-backups`) and `--keep N` (default 7)
- `pg_dump --format=custom "$DATABASE_URL"` to `flightdata-YYYYmmdd-HHMM.dump`
- delete all but the newest N dumps (`ls -1t | tail -n +$((N+1))`)
- non-zero exit if the dump is empty
- passes `shellcheck scripts/backup_db.sh`

Test a restore into a scratch database with `pg_restore --dbname=...`. Add the script to the
CI ShellCheck step (it already globs `scripts/*.sh`).

## Useful commands

| Task | Command |
|---|---|
| Live logs | `journalctl -u fda-ingest -f` |
| Run a poll now | `sudo systemctl start fda-ingest.service` |
| Pause collection | `sudo systemctl stop fda-ingest.timer` |
| Disk used by data | `psql "$DATABASE_URL" -c "SELECT pg_size_pretty(pg_database_size('flightdata'))"` |
| Report to file | `python -m fda.analyze --days 7 --markdown reports/week1.md` |
| Uninstall timer | `sudo systemctl disable --now fda-ingest.timer && sudo rm /etc/systemd/system/fda-ingest.*` |
