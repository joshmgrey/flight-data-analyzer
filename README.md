# Flight Data Analyzer

Collects live ADS-B state vectors from the [OpenSky Network](https://opensky-network.org)
for the airspace around **Atlantic City International Airport (ACY)**, home of the FAA
William J. Hughes Technical Center. It stores them in PostgreSQL, flags bad data, and reports
traffic, altitude and phase-of-flight patterns, data quality and coverage gaps.

It runs unattended on Ubuntu as a systemd timer, with Bash scripts for setup, health checks
and log inspection. It is documented the way a systems-engineering program would expect:
numbered requirements, an interface control document, a verification traceability matrix
and an FMEA.

![CI](https://github.com/joshmgrey/flight-data-analyzer/actions/workflows/ci.yml/badge.svg)

```
           every 5 min (systemd timer)
                    │
OpenSky REST ──▶ fda.ingest ──▶ validate + classify ──▶ PostgreSQL ──▶ fda.analyze ──▶ Markdown report
 /states/all     retry, rate    6 data-quality flags      poll_runs       7 SQL analyses
 (ACY box)       guard, lock    phase of flight, band     state_vectors
                    │                                          ▲
                    └── one key=value log line ─▶ journald ─▶ inspect_logs.sh
                                                  healthcheck.sh ──┘
```

## Contents

| Path | What |
|---|---|
| `src/fda/` | Python package: OpenSky client, parsing, validation, phase classification, storage, analyses, health |
| `src/fda/sql/` | Schema and the seven analysis queries |
| `scripts/` | `setup.sh` (idempotent provisioning), `healthcheck.sh`, `inspect_logs.sh` |
| `deploy/` | systemd service and timer, cron alternative, env file template |
| `tests/` | 122 pytest tests: unit, data-validation, database and end-to-end ingest |
| `docs/` | [Requirements](docs/REQUIREMENTS.md) · [ICD](docs/ICD.md) · [RVTM](docs/RVTM.md) · [Risk register / FMEA](docs/RISK_REGISTER.md) · [Linux runbook](docs/LINUX_RUNBOOK.md) |

## Quick start (Ubuntu 22.04+, WSL2 or EC2)

```bash
git clone https://github.com/joshmgrey/flight-data-analyzer.git ~/flight-data-analyzer
cd ~/flight-data-analyzer
bash scripts/setup.sh          # installs PostgreSQL, venv, /etc/fda/fda.env, schema, timer
scripts/healthcheck.sh         # after ~10 minutes
scripts/inspect_logs.sh        # summary of the last 24 h of polls
.venv/bin/python -m fda.analyze --days 7 --markdown reports/week1.md   # needs DATABASE_URL loaded
```

The [Linux runbook](docs/LINUX_RUNBOOK.md) walks through the same deployment by hand first,
plus failure drills.

## How it works

**Ingest** (`fda.ingest`, one run per timer tick). Takes a PostgreSQL advisory lock so runs
never overlap. Skips if the last attempt was too recent, to stay within the 400-credit/day
anonymous OpenSky budget. Requests `/states/all` for a box of roughly 45 km around ACY.
On 429 it stops; on 5xx or network errors it retries twice with backoff; on an unexpected
body it records a `schema_error`. It then parses and validates each row and stores it with
its flags, phase of flight and altitude band. Every attempt, successful or not, is a row in
`poll_runs`.

**Data quality.** Rows with a bad ICAO address, missing `last_contact` or wrong types are
rejected and counted. Stored rows can carry these flags: `MISSING_POSITION`,
`OUTSIDE_BBOX`, `STALE_POSITION` (position more than 60 s old), `IMPLAUSIBLE_ALTITUDE`,
`IMPLAUSIBLE_SPEED`, and `IMPOSSIBLE_JUMP` (implied speed from the aircraft's previous fix
above 400 m/s). Flagged rows are kept, so analyses can be run with and without them.

**Analyses** (`src/fda/sql/analyses/`): poll outcomes and availability, aircraft in view by
hour of day, hourly traffic, altitude band × phase of flight, data-quality flag rates,
coverage gaps, and operators by callsign.

## Findings

> **To be completed after at least 7 days of collection.** Generate the report with
> `python -m fda.analyze --days 7 --markdown reports/<dates>.md`, commit it, and replace
> each placeholder below with numbers from that report. Keep every claim traceable to a
> table in the report.

**Collection window:** `<start>` to `<end>` (America/New_York), host `<WSL2 | EC2>`.

**Collection availability.** `<ok polls>` of `<expected polls>` polls succeeded
(`<n>%`). `<n>` rate-limited, `<n>` upstream errors. Longest gap `<n>` min on `<date>`,
cause `<cause>`. *(01_poll_summary, 06_coverage_gaps)*

**Traffic pattern.** On average `<n>` aircraft were in view per poll. The busiest local
hour was `<hh>:00` (`<n>` on average, peak `<n>`) and the quietest was `<hh>:00`.
*(02_traffic_by_hour_of_day)*

**Altitude and phase.** `<n>%` of observations were below 3,000 ft and `<n>%` at or above
FL290. `<observation about overflights vs. ACY arrivals and departures>`. Phase shares are
heuristic (risk R-10). *(04_altitude_phase)*

**Traffic mix.** `<n>` distinct airline designators; top three `<AAL, JBU, ...>`.
N-number (mostly general aviation) callsigns were `<n>%` of distinct aircraft.
*(07_operators)*

**Data quality.** `<n>%` of stored records had no flags. The most common flag was `<flag>`
(`<n>%`). `<n>` `IMPOSSIBLE_JUMP` records, `<describe one example you looked at>`.
`<n>` rows were rejected outright. *(05_data_quality)*

**Limitations.** OpenSky coverage depends on volunteer receivers, so low-altitude traffic
near ACY is likely under-counted. `<WSL gaps, if any>`. The phase-of-flight rules are
single-sample heuristics.

## Tests and CI

```bash
pip install -e ".[dev]"
pytest -q                                            # unit + data-validation (DB tests skip)
TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/fda_test pytest -q   # everything
```

Database tests run in a throwaway schema per test, so they never touch production tables.
GitHub Actions runs ruff, all tests against PostgreSQL 16 (failing on any skipped database
test or coverage below 85%), ShellCheck, `bash -n` and `systemd-analyze verify`.
Each requirement maps to its tests in the [RVTM](docs/RVTM.md).

## Data source and terms

State vectors come from the OpenSky Network REST API, used anonymously or with a free
account, for non-commercial, educational purposes under the
[OpenSky terms of use](https://opensky-network.org/about/terms-of-use). Requests identify the
project in their User-Agent and stay within the published rate limits (288 of 400 daily
credits when anonymous).

> Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic and Matthias
> Wilhelm. "Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research".
> In *Proceedings of the 13th IEEE/ACM International Symposium on Information Processing
> in Sensor Networks (IPSN)*, pages 83–94, April 2014.

This is a portfolio project, not an operational tool. Nothing here should be used for
navigation, separation or any safety decision.

## License

MIT
