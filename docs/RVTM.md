# Flight Data Analyzer: Requirements Verification Traceability Matrix

| | |
|---|---|
| Document | FDA-RVTM-001 |
| Version | 0.1 (draft) |
| Date | 2026-10-27 |
| Related | [Requirements](REQUIREMENTS.md) · [ICD](ICD.md) · [Risk register](RISK_REGISTER.md) |

Methods: **T** test, **D** demonstration, **I** inspection, **A** analysis.
Test IDs are pytest node IDs under `tests/` (file `::` function). Parametrized tests count
as one test ID here.

**Status key.** *Pass (CI)*: passed in GitHub Actions on Ubuntu 24.04 against PostgreSQL 16;
first green run [40606373171](https://github.com/joshmgrey/flight-data-analyzer/actions/runs/40606373171)
on 2026-10-28.
*Open*: not yet performed. Record the date and evidence when a status changes.

## 1. Matrix

| Req | Summary | V | Verified by | Status |
|---|---|---|---|---|
| FDA-001 | Bounding box, ACY default | T | `test_config.py::test_default_bbox_contains_acy_and_excludes_phl`, `test_config.py::test_bbox_override_parsed`, `test_opensky_client.py::test_request_uses_bbox_and_extended` | Pass (CI) |
| FDA-002 | Reject bad / oversized box | T | `test_config.py::test_invalid_bbox_rejected` | Pass (CI) |
| FDA-003 | Interval floors 300 s / 60 s | T | `test_config.py::test_anonymous_interval_floor_enforced`, `test_config.py::test_authenticated_interval_floor_is_lower`, `test_config.py::test_anonymous_daily_credit_budget_fits` | Pass (CI) |
| FDA-004 | Rate guard | T | `test_ingest.py::test_rate_guard_skips_early_poll`, `test_ingest.py::test_rate_guard_allows_poll_after_interval` | Pass (CI) |
| FDA-005 | 429: no retry, `rate_limited` | T | `test_opensky_client.py::test_429_raises_rate_limited_without_retry`, `test_ingest.py::test_rate_limited_poll_recorded` | Pass (CI) |
| FDA-006 | 5xx / network retry and backoff | T | `test_opensky_client.py::test_5xx_retried_with_backoff_then_succeeds`, `test_opensky_client.py::test_5xx_gives_up_after_max_retries`, `test_opensky_client.py::test_network_error_retried_then_raised`, `test_ingest.py::test_upstream_failure_recorded` | Pass (CI) |
| FDA-007 | Other 4xx not retried | T | `test_opensky_client.py::test_4xx_not_retried` | Pass (CI) |
| FDA-008 | Malformed body → `schema_error` | T | `test_opensky_client.py::test_malformed_body_raises_schema_error`, `test_ingest.py::test_schema_change_recorded` | Pass (CI) |
| FDA-009 | OAuth2 when configured | T | `test_opensky_client.py::test_oauth_token_fetched_once_and_reused`, `test_opensky_client.py::test_anonymous_sends_no_auth_header`, `test_opensky_client.py::test_token_failure_is_upstream_error` | Pass (CI) |
| FDA-010 | User-Agent, non-commercial use | I | I-1: `opensky.py` `USER_AGENT`; README "Data source and terms" | Open |
| FDA-011 | `states: null` is a valid empty poll | T | `test_opensky_client.py::test_null_states_means_empty_sky` | Pass (CI) |
| FDA-020 | Store every ICD field | T | `test_models.py::test_parse_real_sample`, `test_db.py::test_insert_roundtrip_preserves_fields_in_utc`, `test_ingest.py::test_real_sample_ingested_end_to_end` | Pass (CI) |
| FDA-021 | UTC `timestamptz` | T | `test_db.py::test_insert_roundtrip_preserves_fields_in_utc` | Pass (CI) |
| FDA-022 | No duplicate (icao24, time) | T | `test_db.py::test_duplicate_vector_ignored`, `test_models.py::test_parse_states_counts_rejections_and_duplicates` | Pass (CI) |
| FDA-023 | DB domain constraints | T | `test_db.py::test_schema_constraints_reject_bad_values` | Pass (CI) |
| FDA-024 | Every poll recorded | T | `test_db.py::test_poll_lifecycle_recorded`, `test_ingest.py::test_real_sample_ingested_end_to_end`, `test_ingest.py::test_rate_limited_poll_recorded` | Pass (CI) |
| FDA-025 | Idempotent schema | T | `test_db.py::test_schema_is_idempotent` | Pass (CI) |
| FDA-026 | Retention purge | T | `test_db.py::test_purge_removes_old_polls_and_their_vectors` | Pass (CI) |
| FDA-027 | One poll at a time | T | `test_db.py::test_ingest_lock_is_exclusive`, `test_ingest.py::test_overlapping_run_skipped_when_locked` | Pass (CI) |
| FDA-030 | Reject malformed rows, count them | T | `test_models.py::test_bad_rows_rejected`, `test_models.py::test_short_row_rejected`, `test_models.py::test_parse_states_counts_rejections_and_duplicates`, `test_ingest.py::test_flagged_and_rejected_records` | Pass (CI) |
| FDA-031 | `MISSING_POSITION` | T | `test_validate.py::test_missing_position` | Pass (CI) |
| FDA-032 | `OUTSIDE_BBOX` | T | `test_validate.py::test_outside_bbox`, `test_validate.py::test_real_sample_flags` | Pass (CI) |
| FDA-033 | `STALE_POSITION` > 60 s | T | `test_validate.py::test_stale_position_threshold`, `test_validate.py::test_null_time_position_not_stale`, `test_validate.py::test_real_sample_flags` | Pass (CI) |
| FDA-034 | `IMPLAUSIBLE_ALTITUDE` | T | `test_validate.py::test_implausible_altitude` | Pass (CI) |
| FDA-035 | `IMPLAUSIBLE_SPEED` | T | `test_validate.py::test_implausible_speed` | Pass (CI) |
| FDA-036 | `IMPOSSIBLE_JUMP` | T | `test_validate.py::test_jump_detected_for_teleport`, `test_validate.py::test_normal_motion_not_a_jump`, `test_validate.py::test_jump_skipped_when_times_not_comparable`, `test_validate.py::test_jump_needs_history`, `test_validate.py::test_haversine_known_distance`, `test_db.py::test_previous_fixes_returns_latest_non_jump_fix`, `test_ingest.py::test_impossible_jump_flagged_across_polls` | Pass (CI) |
| FDA-037 | Flagged records kept with all flags | T | `test_validate.py::test_multiple_flags_accumulate`, `test_ingest.py::test_flagged_and_rejected_records` | Pass (CI) |
| FDA-040 | Phase of flight | T | `test_phase.py::test_classify_phase` | Pass (CI) |
| FDA-041 | Altitude band | T | `test_phase.py::test_altitude_band` | Pass (CI) |
| FDA-042 | Hourly and hour-of-day traffic | T | `test_analyze.py::test_hourly_traffic`, `test_analyze.py::test_hourly_traffic_uses_local_time`, `test_analyze.py::test_traffic_by_hour_of_day` | Pass (CI) |
| FDA-043 | Band × phase breakdown | T | `test_analyze.py::test_altitude_phase`, `test_analyze.py::test_altitude_phase_ordering_and_percentages` | Pass (CI) |
| FDA-044 | Data-quality summary | T | `test_analyze.py::test_data_quality` | Pass (CI) |
| FDA-045 | Coverage gaps | T | `test_analyze.py::test_coverage_gaps` | Pass (CI) |
| FDA-046 | Poll outcome summary | T | `test_analyze.py::test_poll_summary` | Pass (CI) |
| FDA-047 | Operator mix | T | `test_analyze.py::test_operators` | Pass (CI) |
| FDA-048 | Markdown report | T | `test_analyze.py::test_markdown_report`, `test_analyze.py::test_all_analyses_discovered`, `test_analyze.py::test_empty_window_returns_no_rows` | Pass (CI) |
| FDA-050 | Unattended on Ubuntu via systemd timer | D, I | D-1; I-2 (CI `systemd-analyze verify`) | I: Pass (CI); D: Open |
| FDA-051 | Catch-up poll after downtime | D | D-2 | Open |
| FDA-052 | One key=value log line per poll | T, D | `test_ingest.py::test_poll_log_line_is_greppable`; D-3 | T: Pass (CI); D: Open |
| FDA-053 | Distinct exit codes | T | `test_exit_codes.py::test_exit_codes_are_distinct`, `test_exit_codes.py::test_ingest_config_error_without_database_url`, `test_exit_codes.py::test_ingest_db_error_when_unreachable` | Pass (CI) |
| FDA-054 | Health check | T, D | `test_health.py::test_unhealthy_when_no_polls`, `test_health.py::test_healthy_with_recent_ok_poll`, `test_health.py::test_unhealthy_when_only_recent_polls_failed`, `test_exit_codes.py::test_health_reports_unreachable_database`; D-4 | T: Pass (CI); D: Open |
| FDA-055 | Secrets out of repo, env file 600 | I, D | I-3; D-1 step 4 | Open |
| FDA-056 | Idempotent setup | D | D-5 | Open |
| FDA-057 | Unprivileged, sandboxed service | I | I-4 | Open |
| FDA-060 | Tests in CI, fail on skip / <85% | I | I-5 | Pass (CI) |
| FDA-061 | Shell and unit linting in CI | I | I-2, I-5 | Pass (CI) |

## 2. Demonstrations

Perform each on the deployment host (WSL2 Ubuntu or EC2). Record date, host, the commands'
output (paste or screenshot into `docs/evidence/`), and Pass/Fail.

| ID | Procedure | Pass criteria | Date / result |
|---|---|---|---|
| D-1 | Fresh host: clone repo under `~`, run `scripts/setup.sh`. Then `systemctl list-timers fda-ingest.timer`, wait 15 min, `journalctl -u fda-ingest -n 5`, and `ls -l /etc/fda/fda.env`. | Timer listed with next run ≤ 5 min away; ≥ 2 `poll status=ok` lines 5 min apart; env file `-rw-------` owned by service user. | |
| D-2 | `sudo systemctl stop fda-ingest.timer`, wait past a scheduled run (or shut WSL down: `wsl --shutdown`), then start the timer / reopen Ubuntu. | `journalctl -u fda-ingest` shows a poll within 1 minute of restart. | |
| D-3 | After ≥ 24 h of collection run `scripts/inspect_logs.sh`. | Status counts and averages printed; counts match `SELECT status, count(*) FROM poll_runs ... GROUP BY 1` for the same window. | |
| D-4 | Run `scripts/healthcheck.sh` while healthy (expect exit 0). Then `sudo systemctl stop fda-ingest.timer`, wait 16 min, re-run (expect FAIL timer + freshness, exit 1). Then `sudo systemctl stop postgresql` and re-run (expect FAIL postgres, exit 1). Restore both. | Exit codes and FAIL lines as stated. | |
| D-5 | Run `scripts/setup.sh` a second time on the configured host. | No errors; `fda.env` unchanged (`sha256sum` before/after); row counts unchanged. | |

## 3. Inspections

| ID | Item | Criteria |
|---|---|---|
| I-1 | `src/fda/opensky.py`, README | Descriptive User-Agent set; README states non-commercial use and OpenSky attribution. |
| I-2 | CI job `shell` | `systemd-analyze verify` passes for both units. |
| I-3 | `.gitignore`, `scripts/setup.sh`, `deploy/` | `*.env` ignored; only `fda.env.example` committed; setup applies `chmod 600`; no secrets in unit files. `git log -p | grep -i password` finds nothing but placeholders. |
| I-4 | `deploy/systemd/fda-ingest.service` | `User=` non-root; `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp` set. |
| I-5 | `.github/workflows/ci.yml` and a green run | Triggers on push and pull_request; Postgres 16 service; `--cov-fail-under=85`; skipped-DB-test guard; ShellCheck and `bash -n` steps. |

## 4. Coverage summary

46 requirements. 38 have automated tests, all passing in CI on 2026-10-28 (122 tests,
36 of them database tests with none skipped, 92% line coverage); 36 of those are fully
verified by test, while FDA-052 and FDA-054 also need a demonstration. Of the 8 verified by
demonstration or inspection only, FDA-060 and FDA-061 are closed by the CI run (I-2, I-5);
FDA-010, 050 (demonstration part), 051, 055, 056 and 057 stay open until performed on the
deployment host. Every requirement has at least one
verification method.
