# Flight Data Analyzer: Risk Register and FMEA

| | |
|---|---|
| Document | FDA-RISK-001 |
| Version | 0.1 (draft) |
| Date | 2026-10-27 |
| Related | [Requirements](REQUIREMENTS.md) · [RVTM](RVTM.md) |

## 1. Method

A process FMEA over the data path (acquire → validate → store → analyze → operate).
Each failure mode is rated 1–10 for:

| | 1 | 5 | 10 |
|---|---|---|---|
| **S**everity | No visible effect | Some data lost or a statistic biased; recoverable | Silent corruption, or wrong conclusions published |
| **O**ccurrence | Not expected in a year | About monthly | Every day |
| **D**etection | Detected and handled automatically | Visible on routine review (report, health check) | Undetectable with current controls |

**RPN** = S × O × D (max 1000). Items with RPN ≥ 80 or S ≥ 7 need an action. Ratings are
the author's engineering estimates before field data; revisit them after two weeks of
operation using `poll_runs` (section 4).

## 2. FMEA

| ID | Function | Failure mode | Effect | Cause | S | O | D | RPN | Current controls | Reqs | Action / owner |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R-01 | Acquire | OpenSky returns 5xx or times out | Missed poll; gap in data | OpenSky outage or maintenance; no SLA | 4 | 4 | 2 | 32 | 2 retries with backoff; `upstream_error` recorded; coverage-gap report; health check freshness | FDA-006, 045, 054 | Accept. |
| R-02 | Acquire | Daily credits exhausted (HTTP 429) | No data until UTC midnight reset | Interval misconfigured, manual runs, overlapping jobs | 5 | 3 | 2 | 30 | Interval floor at startup; rate guard; advisory lock; no retry on 429; `credits_remaining` logged | FDA-003, 004, 005, 027 | Accept. Watch `min_credits_remaining` in poll summary. |
| R-03 | Acquire | Response format changes | Polls fail or fields mis-mapped | OpenSky API change | 6 | 2 | 2 | 24 | Strict parse; `schema_error` stored with message; per-row type checks reject instead of guessing; ICD documents expected format | FDA-008, 030 | Accept. |
| R-04 | Operate | Host not running at poll time | Hours of missing data | **WSL2 can stop the distro when no Windows terminal or process keeps it alive**; laptop sleep; EC2 stop | 6 | 7 | 3 | **126** | `Persistent=true` catch-up poll; coverage-gap report quantifies loss; health check | FDA-045, 051 | **Open.** For multi-day collection run on a small always-on EC2 instance, or keep a WSL session open and disable sleep. Report coverage % alongside every finding. |
| R-05 | Store | PostgreSQL down or refuses connections | Poll fails with exit 4; no data | Service stopped, disk full, bad password after re-provision | 6 | 2 | 2 | 24 | Unit ordered `After=postgresql`; exit code 4; health check `pg_isready` and DB query | FDA-053, 054 | Accept. |
| R-06 | Store | Disk fills | PostgreSQL stops accepting writes; possible host instability | Unbounded growth (~300 rows per poll at peak) | 7 | 2 | 3 | 42 | Retention purge each poll (30 days); health check WARN 80%, FAIL 90% | FDA-026, 054 | S ≥ 7: verify purge after first 30 days (D-3 follow-up). |
| R-07 | Store | Duplicate or overlapping polls | Double-counted traffic | Timer and manual run at once; cron overlap | 4 | 2 | 2 | 16 | `pg_try_advisory_lock`; `Type=oneshot`; unique (icao24, api_time) | FDA-022, 027 | Accept. |
| R-08 | Validate | Bad ADS-B content: position jumps, impossible altitude or speed, spoofed or corrupted messages | Biased statistics; false traffic | Transponder faults, decoder errors, MLAT artifacts, spoofing | 5 | 6 | 3 | 90 | Six data-quality flags; records kept with flags; DQ report gives rates | FDA-031–037, 044 | **Open.** Report findings with and without flagged records. Known gap: slow, consistent spoofing within speed limits is not detected. |
| R-09 | Validate | Stale positions or receiver coverage holes | Aircraft shown where they were, not where they are; low counts at low altitude | Few volunteer receivers near ACY; terrain/line-of-sight | 4 | 7 | 3 | 84 | `STALE_POSITION` flag; zero-aircraft poll count; altitude-band report shows low-altitude under-coverage | FDA-033, 043, 046 | **Open.** State coverage limits in findings; compare low-altitude counts against known ACY operations before drawing conclusions. |
| R-10 | Analyze | Phase-of-flight misclassification | Wrong climb/descent/cruise shares | Single-sample vertical rate; baro altitude not corrected to AGL; no hysteresis | 3 | 6 | 6 | **108** | Rules documented in ICD; boundary unit tests | FDA-040 | **Open.** Label phase statistics as heuristic. Possible fix: classify on a 3-sample median vertical rate. |
| R-11 | Operate | Host clock skew | Wrong `poll_runs` times; rate guard misfires | No time sync on host or WSL drift after sleep | 3 | 3 | 5 | 45 | Analyses use OpenSky `time`, not host time | – | Check `timedatectl` shows "System clock synchronized: yes" during D-1. |
| R-12 | Operate | Credentials leaked | Database or OpenSky account misuse | Secret committed to git or pasted into logs | 7 | 2 | 4 | 56 | Env file mode 600 outside repo; `*.env` gitignored; secrets never logged | FDA-055 | S ≥ 7: perform I-3 before making the repo public. |
| R-13 | Operate | Process killed mid-poll | `poll_runs` row stuck at `running`; partial batch | OOM kill, `TimeoutStartSec` hit, reboot | 2 | 2 | 3 | 12 | Status stays `running` and shows in poll summary; a poll's inserts commit in one transaction, so no partial batch is stored | FDA-024 | Accept. |
| R-14 | Acquire | Terms-of-use breach | Access blocked; reputational harm | Commercial use, polling above limits | 6 | 1 | 3 | 18 | Interval floors; User-Agent; README terms | FDA-003, 010 | Accept. |

## 3. Top risks

1. **R-04 Host availability (RPN 126).** The largest threat to the data is the host itself,
   especially on WSL2. Mitigation is operational: collect on an always-on host and report
   collection coverage with every finding.
2. **R-10 Phase classification (RPN 108).** Low impact but hard to detect. Treat phase
   statistics as approximate.
3. **R-08 Bad ADS-B data (RPN 90)** and **R-09 coverage holes (RPN 84).** Both are measured
   rather than prevented; findings must state the flag rates and coverage they rest on.

## 4. Reliability and maintainability measures

Computed from `poll_runs` over the analysis window, so they come from observed operation,
not estimates:

| Measure | Definition | Query / source | Target |
|---|---|---|---|
| Collection availability | `ok` polls ÷ expected polls (window ÷ 300 s) | `01_poll_summary` | ≥ 95% on EC2; report actual on WSL |
| Upstream failure rate | (`upstream_error` + `schema_error`) ÷ all polls | `01_poll_summary` | Report |
| Longest outage | Max gap between `ok` polls | `06_coverage_gaps` | Report, with cause if known |
| Mean time to restore | Mean gap length for gaps > 10 min | `06_coverage_gaps` | Report |
| Clean-record rate | Records with no flags ÷ stored records | `05_data_quality` | Report |
| Credit headroom | Min `credits_remaining` per day | `01_poll_summary` | > 50 |

Maintainability provisions: schema as code and idempotent (`python -m fda.db init`);
idempotent provisioning (`scripts/setup.sh`); one summary log line per poll with a documented
format (ICD 4.3); health check and log-inspection scripts; 122 automated tests run in CI;
this document, the ICD and the RVTM are updated in the same change as the code they describe.

## 5. Revision history

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-10-27 | Initial ratings before deployment. |
