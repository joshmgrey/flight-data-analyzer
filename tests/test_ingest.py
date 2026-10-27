"""End-to-end ingest cycles against a real PostgreSQL schema and a fake OpenSky."""

import logging
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from fda import db, ingest
from fda.config import Settings
from fda.opensky import OpenSkyClient
from fda.validate import IMPOSSIBLE_JUMP, MISSING_POSITION, OUTSIDE_BBOX, STALE_POSITION
from tests.conftest import SAMPLE_API_TIME, FakeResponse, FakeSession, raw_row

pytestmark = pytest.mark.db

T = SAMPLE_API_TIME
NOW = datetime.fromtimestamp(T, tz=timezone.utc)
SETTINGS = Settings(database_url="unused")


def run(conn, *responses, now=NOW, settings=SETTINGS):
    client = OpenSkyClient(session=FakeSession(gets=list(responses)), sleep=lambda s: None)
    return ingest.run_once(settings, conn, client, now=now)


def body(*svs, api_time=T):
    return {"time": api_time, "states": [raw_row(sv) for sv in svs]}


def polls(conn):
    return conn.execute(
        "SELECT status, http_status, n_states, n_inserted, n_rejected, n_flagged, "
        "credits_remaining FROM poll_runs ORDER BY id"
    ).fetchall()


def test_real_sample_ingested_end_to_end(db_conn, sample_body):
    out = run(db_conn, FakeResponse(200, sample_body, {"X-Rate-Limit-Remaining": "399"}))
    assert out.status == "ok" and out.exit_code == ingest.EXIT_OK
    assert out.n_inserted == 33

    assert polls(db_conn) == [("ok", 200, 33, 33, 0, out.n_flagged, 399)]
    phases = dict(db_conn.execute(
        "SELECT flight_phase, count(*) FROM state_vectors GROUP BY 1").fetchall())
    on_ground = sum(1 for row in sample_body["states"] if row[8])
    assert phases["GROUND"] == on_ground > 0  # PHL ramp traffic in the captured sample
    flagged = dict(db_conn.execute(
        "SELECT icao24, dq_flags FROM state_vectors WHERE cardinality(dq_flags) > 0"
    ).fetchall())
    assert STALE_POSITION in flagged["ae649c"]
    assert OUTSIDE_BBOX in flagged["a88075"]


def test_flagged_and_rejected_records(db_conn, make_sv):
    bad_row = raw_row(make_sv(icao24="b00000"))
    bad_row[0] = "NOTHEX"
    resp = body(make_sv(), make_sv(icao24="c00000", latitude=None, longitude=None))
    resp["states"].append(bad_row)

    out = run(db_conn, FakeResponse(200, resp))
    assert (out.n_inserted, out.n_rejected, out.n_flagged) == (2, 1, 1)
    stored = dict(db_conn.execute("SELECT icao24, dq_flags FROM state_vectors").fetchall())
    assert stored == {"a1b2c3": [], "c00000": [MISSING_POSITION]}


def test_impossible_jump_flagged_across_polls(db_conn, make_sv):
    run(db_conn, FakeResponse(200, body(make_sv(time_position=T - 2))))
    later = T + 300
    teleport = make_sv(api_time=later, time_position=later, last_contact=later, latitude=39.80,
                       longitude=-74.20)
    # 300 s later the aircraft is ~50 km away: 165 m/s, plausible.
    run(db_conn, FakeResponse(200, body(teleport, api_time=later)),
        now=NOW + timedelta(seconds=300))
    t3 = later + 5
    # 5 s after that it is back near ACY: thousands of m/s.
    back = make_sv(api_time=t3, time_position=t3, last_contact=t3)
    run(db_conn, FakeResponse(200, body(back, api_time=t3)), now=NOW + timedelta(seconds=600))

    flags = [r[0] for r in db_conn.execute(
        "SELECT dq_flags FROM state_vectors ORDER BY api_time").fetchall()]
    assert flags == [[], [], [IMPOSSIBLE_JUMP]]


def test_rate_limited_poll_recorded(db_conn):
    out = run(db_conn, FakeResponse(429, None, {"X-Rate-Limit-Retry-After-Seconds": "120"}))
    assert out.exit_code == ingest.EXIT_RATE_LIMITED
    assert polls(db_conn) == [("rate_limited", 429, None, None, None, None, None)]


def test_upstream_failure_recorded(db_conn):
    out = run(db_conn, FakeResponse(503), FakeResponse(503), FakeResponse(503))
    assert out.exit_code == ingest.EXIT_UPSTREAM
    assert polls(db_conn)[0][:2] == ("upstream_error", 503)


def test_schema_change_recorded(db_conn):
    out = run(db_conn, FakeResponse(200, {"flights": []}))
    assert out.exit_code == ingest.EXIT_UPSTREAM
    assert polls(db_conn)[0][0] == "schema_error"


def test_rate_guard_skips_early_poll(db_conn, make_sv):
    run(db_conn, FakeResponse(200, body(make_sv())))
    session = FakeSession()
    client = OpenSkyClient(session=session)
    out = ingest.run_once(SETTINGS, db_conn, client, now=NOW + timedelta(seconds=120))
    assert out.status == "skipped"
    assert session.get_calls == []
    assert len(polls(db_conn)) == 1


def test_rate_guard_allows_poll_after_interval(db_conn, make_sv):
    run(db_conn, FakeResponse(200, body(make_sv())))
    out = run(db_conn, FakeResponse(200, body(make_sv(), api_time=T + 295)),
              now=NOW + timedelta(seconds=295))  # within timer-jitter tolerance
    assert out.status == "ok"


def test_overlapping_run_skipped_when_locked(db_conn):
    holder = psycopg.connect(db_conn.info.dsn, password=db_conn.info.password)
    try:
        assert db.try_ingest_lock(holder)
        session = FakeSession()
        out = ingest.run_once(SETTINGS, db_conn, OpenSkyClient(session=session), now=NOW)
        assert out.status == "skipped"
        assert session.get_calls == []
    finally:
        holder.close()


def test_poll_log_line_is_greppable(db_conn, make_sv, caplog):
    with caplog.at_level(logging.INFO, logger="fda.ingest"):
        run(db_conn, FakeResponse(200, body(make_sv()), {"X-Rate-Limit-Remaining": "12"}))
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("poll "))
    for token in ("status=ok", "states=1", "inserted=1", "credits_remaining=12", "duration_ms="):
        assert token in line
