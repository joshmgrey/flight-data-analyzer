# Flight Data Analyzer: System Requirements Specification

| | |
|---|---|
| Document | FDA-SRS-001 |
| Version | 0.1 (draft) |
| Date | 2026-10-27 |
| Author | Joshua Grey |
| Related | [ICD](ICD.md) · [RVTM](RVTM.md) · [Risk register / FMEA](RISK_REGISTER.md) |

## 1. Purpose and scope

Flight Data Analyzer (FDA) collects ADS-B state vectors from the OpenSky Network for the
airspace around Atlantic City International Airport (ACY), stores them in PostgreSQL, checks
their quality and produces traffic statistics. It is a single-host, non-commercial portfolio
system. It is not an operational air traffic tool, and nothing it produces should be used for
separation, navigation or safety decisions.

## 2. Conventions

- Each requirement has a unique ID `FDA-nnn` and uses "shall". IDs are never reused.
- Verification methods (column **V**): **T** test, **D** demonstration, **I** inspection,
  **A** analysis. The [RVTM](RVTM.md) maps each requirement to its verification.
- "Poll" means one execution of the ingest job. "Accepted record" means a state vector that
  passed FDA-030 and was offered to the database.
- Units are SI (metres, metres per second, seconds) unless stated otherwise.

## 3. Requirements

### 3.1 Data acquisition (interface IF-1, see ICD section 2)

| ID | Requirement | V |
|---|---|---|
| FDA-001 | The system shall request state vectors from the OpenSky `/states/all` endpoint restricted to a configurable bounding box, defaulting to 39.05–39.85 N, 74.10–75.05 W around ACY. | T |
| FDA-002 | The system shall refuse to start with a bounding box that is malformed, inverted, or larger than 25 square degrees. | T |
| FDA-003 | The system shall refuse to start with a configured poll interval below 300 s for anonymous access or 60 s for authenticated access. | T |
| FDA-004 | The system shall not send a request to OpenSky if the previous poll attempt started less than the minimum interval (FDA-003) minus 10 s earlier. | T |
| FDA-005 | When OpenSky returns HTTP 429, the system shall make no further request in that poll and shall record the poll as `rate_limited`. | T |
| FDA-006 | When OpenSky returns HTTP 5xx or the request fails at the network level, the system shall retry at most 2 times with exponential backoff (2 s, then 4 s) and, if all attempts fail, record the poll as `upstream_error`. | T |
| FDA-007 | The system shall not retry a request that receives an HTTP 4xx response other than 429. | T |
| FDA-008 | When the response body does not match ICD section 2.4, the system shall record the poll as `schema_error` and store no state vectors from it. | T |
| FDA-009 | When an OpenSky client ID and secret are configured, the system shall authenticate with an OAuth2 client-credentials bearer token, reusing the token until 30 s before it expires; otherwise it shall send no credentials. | T |
| FDA-010 | The system shall identify itself to OpenSky with a descriptive User-Agent and shall be used only for non-commercial purposes, per the OpenSky terms of use. | I |
| FDA-011 | The system shall treat a response whose `states` value is null as a successful poll with zero aircraft. | T |

### 3.2 Storage (interface IF-2, see ICD section 3)

| ID | Requirement | V |
|---|---|---|
| FDA-020 | The system shall store every accepted record in PostgreSQL with every field defined in ICD section 3.2. | T |
| FDA-021 | The system shall store all timestamps as `timestamptz` in UTC, converted from OpenSky Unix epoch seconds. | T |
| FDA-022 | The system shall store at most one record per aircraft (`icao24`) per OpenSky response time. | T |
| FDA-023 | The database shall reject values outside the domains defined in ICD section 3 (ICAO address format, coordinate ranges, enumerations). | T |
| FDA-024 | The system shall record every poll attempt in `poll_runs` with start and finish time, outcome, HTTP status, record counts, remaining API credits and duration. | T |
| FDA-025 | Applying the database schema shall be idempotent. | T |
| FDA-026 | The system shall delete polls, and their state vectors, older than a configurable retention period (default 30 days). | T |
| FDA-027 | The system shall ensure that at most one poll executes at a time, skipping a poll that starts while another holds the lock. | T |

### 3.3 Data validation

| ID | Requirement | V |
|---|---|---|
| FDA-030 | The system shall reject, without storing, any row that has fewer than 17 fields, an `icao24` that is not 6 hexadecimal digits, no `last_contact`, a wrong field type, or a duplicate `icao24` within one response, and shall count rejections in `poll_runs.n_rejected`. | T |
| FDA-031 | The system shall flag a record `MISSING_POSITION` when latitude or longitude is null. | T |
| FDA-032 | The system shall flag a record `OUTSIDE_BBOX` when its position lies outside the configured bounding box. | T |
| FDA-033 | The system shall flag a record `STALE_POSITION` when its `time_position` is more than 60 s older than the response time. | T |
| FDA-034 | The system shall flag a record `IMPLAUSIBLE_ALTITUDE` when barometric altitude is below -300 m or above 18,300 m. | T |
| FDA-035 | The system shall flag a record `IMPLAUSIBLE_SPEED` when ground speed is negative or above 350 m/s. | T |
| FDA-036 | The system shall flag a record `IMPOSSIBLE_JUMP` when the ground speed implied by the distance and time from the same aircraft's most recent stored position (ignoring positions already flagged `IMPOSSIBLE_JUMP`) within the previous 30 minutes exceeds 400 m/s. | T |
| FDA-037 | The system shall store flagged records with all applicable flags rather than discard them. | T |

### 3.4 Analysis

| ID | Requirement | V |
|---|---|---|
| FDA-040 | The system shall classify each record's phase of flight as GROUND, CLIMB, DESCENT, CRUISE, LEVEL or UNKNOWN using the rules in ICD section 3.3. | T |
| FDA-041 | The system shall assign each record an altitude band as defined in ICD section 3.3. | T |
| FDA-042 | The system shall report distinct aircraft and observations per hour, and mean and peak aircraft in view by hour of day, in a configurable time zone defaulting to America/New_York. | T |
| FDA-043 | The system shall report observation counts and percentages by altitude band and phase of flight. | T |
| FDA-044 | The system shall report, for each data-quality flag, the number and percentage of stored records carrying it, and the number with no flags. | T |
| FDA-045 | The system shall report each interval between consecutive successful polls that exceeds twice the nominal poll interval. | T |
| FDA-046 | The system shall report poll counts by outcome, including polls that returned zero aircraft. | T |
| FDA-047 | The system shall report distinct aircraft by operator, derived from the callsign. | T |
| FDA-048 | The system shall render all analyses for a chosen time window as a Markdown report. | T |

### 3.5 Operations, reliability and maintainability

| ID | Requirement | V |
|---|---|---|
| FDA-050 | The system shall run unattended on Ubuntu 22.04 or later, polling every 5 minutes under a systemd timer, with a cron entry as an alternative for hosts without systemd. | D, I |
| FDA-051 | After the host has been off at a scheduled poll time, the system shall run one catch-up poll when it starts again. | D |
| FDA-052 | The system shall write one summary log line per poll to standard output, as `key=value` pairs including status, record counts, remaining credits and duration, so that journald captures it. | T, D |
| FDA-053 | The ingest process shall exit with a distinct status code for each outcome class: success or skip, configuration error, rate limited, upstream error, database error. | T |
| FDA-054 | The health check shall report failure when no successful poll has occurred within a configurable age (default 15 minutes), the database is unreachable, the timer is inactive, or the database disk is at least 90% full. | T, D |
| FDA-055 | The system shall keep credentials out of the source repository, reading them from an environment file readable only by the service user (mode 600). | I, D |
| FDA-056 | The setup script shall be idempotent: running it again on a configured host shall leave the configuration and data intact. | D |
| FDA-057 | The ingest service shall run as an unprivileged user with systemd sandboxing (no new privileges, read-only system and home directories). | I |

### 3.6 Verification

| ID | Requirement | V |
|---|---|---|
| FDA-060 | Automated tests, including database tests against PostgreSQL 16, shall run in CI on every push and pull request, and the build shall fail on any test failure, any skipped database test, or line coverage below 85%. | I |
| FDA-061 | Shell scripts shall pass `bash -n` and ShellCheck, and systemd units shall pass `systemd-analyze verify`, in CI. | I |

## 4. Assumptions and constraints

- OpenSky provides crowd-sourced data on a best-effort basis with no service-level agreement.
  Coverage near ACY depends on volunteer receivers.
- Anonymous OpenSky access allows 400 API credits per day; a query over a box of 25 square
  degrees or less costs 1 credit. At a 300 s interval the system uses 288 credits per day.
- The host clock is synchronized (systemd-timesyncd or chrony). Analyses use the OpenSky
  response time, so host skew affects only `poll_runs` timestamps and the rate guard.
- Phase-of-flight rules are coarse heuristics for aggregate statistics, not per-flight event
  detection.

## 5. Out of scope

Historical data (the OpenSky Trino database), multilateration, per-flight trajectory
reconstruction, real-time alerting, dashboards, and multi-host deployment.
