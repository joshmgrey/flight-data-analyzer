"""One ingest cycle: poll OpenSky once, validate, store. Meant to be run by a systemd timer or cron.

Exit codes (REQ-044):
    0  ok, or skipped because another run holds the lock / the rate guard tripped
    1  configuration error
    2  rate limited by OpenSky (HTTP 429)
    3  upstream error (network, HTTP 5xx after retries, unexpected response format)
    4  database error
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from fda import db
from fda.config import ConfigError, Settings, load_settings
from fda.models import parse_states
from fda.opensky import OpenSkyClient, OpenSkyError, RateLimited, SchemaError
from fda.phase import altitude_band, classify_phase
from fda.validate import IMPOSSIBLE_JUMP, check_record, is_impossible_jump

log = logging.getLogger("fda.ingest")

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_RATE_LIMITED = 2
EXIT_UPSTREAM = 3
EXIT_DB = 4

# Timers fire a few seconds early or late; don't let jitter skip a legitimate poll.
RATE_GUARD_TOLERANCE_S = 10


@dataclass(frozen=True)
class Outcome:
    status: str
    exit_code: int
    n_states: int = 0
    n_inserted: int = 0
    n_rejected: int = 0
    n_flagged: int = 0


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,
    )


def run_once(
    settings: Settings,
    conn: psycopg.Connection,
    client: OpenSkyClient,
    now: datetime | None = None,
) -> Outcome:
    now = now or datetime.now(timezone.utc)

    if not db.try_ingest_lock(conn):
        log.warning("poll status=skipped reason=locked")
        return Outcome("skipped", EXIT_OK)
    try:
        return _run_locked(settings, conn, client, now)
    finally:
        db.release_ingest_lock(conn)
        conn.commit()


def _run_locked(
    settings: Settings, conn: psycopg.Connection, client: OpenSkyClient, now: datetime
) -> Outcome:
    last = db.last_attempt_started_at(conn)
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < settings.min_interval_s - RATE_GUARD_TOLERANCE_S:
            log.warning(
                "poll status=skipped reason=rate_guard elapsed_s=%.0f min_interval_s=%d",
                elapsed, settings.min_interval_s,
            )
            return Outcome("skipped", EXIT_OK)

    t0 = time.monotonic()
    poll_id = db.start_poll(conn, str(settings.bbox), client.authenticated, now)

    def elapsed_ms() -> int:
        return int((time.monotonic() - t0) * 1000)

    try:
        resp = client.fetch_states(settings.bbox)
    except RateLimited as exc:
        db.finish_poll(conn, poll_id, db.PollUpdate(
            "rate_limited", http_status=429, duration_ms=elapsed_ms(), error=str(exc)))
        log.error("poll status=rate_limited retry_after_s=%s", exc.retry_after_s)
        return Outcome("rate_limited", EXIT_RATE_LIMITED)
    except OpenSkyError as exc:
        status = "schema_error" if isinstance(exc, SchemaError) else "upstream_error"
        db.finish_poll(conn, poll_id, db.PollUpdate(
            status, http_status=exc.http_status, duration_ms=elapsed_ms(), error=str(exc)))
        log.error("poll status=%s http_status=%s error=%r", status, exc.http_status, str(exc))
        return Outcome(status, EXIT_UPSTREAM)

    vectors, rejected = parse_states(resp.rows, resp.api_time)
    for reason in rejected:
        log.warning("rejected row reason=%r", reason)

    prev = db.previous_fixes(conn, [v.icao24 for v in vectors], resp.api_time)
    stored: list[db.StoredVector] = []
    for sv in vectors:
        flags = check_record(sv, settings.bbox, settings.stale_position_s)
        if is_impossible_jump(prev.get(sv.icao24), sv):
            flags.append(IMPOSSIBLE_JUMP)
        stored.append(db.StoredVector(
            sv=sv,
            flight_phase=classify_phase(sv.on_ground, sv.baro_altitude_m, sv.vertical_rate_mps),
            altitude_band=altitude_band(sv.on_ground, sv.baro_altitude_m),
            dq_flags=flags,
        ))

    inserted = db.insert_vectors(conn, poll_id, stored)
    purged = db.purge_older_than(conn, settings.retention_days, now)
    conn.commit()

    n_flagged = sum(1 for s in stored if s.dq_flags)
    db.finish_poll(conn, poll_id, db.PollUpdate(
        "ok",
        http_status=resp.http_status,
        api_time=resp.api_time,
        n_states=len(resp.rows),
        n_inserted=inserted,
        n_rejected=len(rejected),
        n_flagged=n_flagged,
        credits_remaining=resp.credits_remaining,
        duration_ms=elapsed_ms(),
    ))
    log.info(
        "poll status=ok states=%d inserted=%d rejected=%d flagged=%d purged_polls=%d "
        "credits_remaining=%s duration_ms=%d",
        len(resp.rows), inserted, len(rejected), n_flagged, purged,
        resp.credits_remaining, elapsed_ms(),
    )
    return Outcome("ok", EXIT_OK, len(resp.rows), inserted, len(rejected), n_flagged)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("config error: %s", exc)
        return EXIT_CONFIG
    configure_logging(settings.log_level)

    client = OpenSkyClient(client_id=settings.client_id, client_secret=settings.client_secret)
    try:
        with db.connect(settings.database_url) as conn:
            return run_once(settings, conn, client).exit_code
    except psycopg.Error as exc:
        log.error("poll status=db_error error=%r", str(exc))
        return EXIT_DB


if __name__ == "__main__":
    sys.exit(main())
