from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from fda import db
from fda.validate import IMPOSSIBLE_JUMP
from tests.conftest import SAMPLE_API_TIME

pytestmark = pytest.mark.db

T = SAMPLE_API_TIME
NOW = datetime.fromtimestamp(T, tz=timezone.utc)


def new_poll(conn, started_at=NOW):
    return db.start_poll(conn, "39.05,-75.05,39.85,-74.1", False, started_at)


def stored(sv, flags=None):
    return db.StoredVector(sv, "LEVEL", "BELOW_3000FT", flags or [])


def test_schema_is_idempotent(db_conn):
    db.apply_schema(db_conn)
    db.apply_schema(db_conn)


def test_insert_roundtrip_preserves_fields_in_utc(db_conn, make_sv):
    sv = make_sv()
    poll = new_poll(db_conn)
    assert db.insert_vectors(db_conn, poll, [stored(sv, ["STALE_POSITION"])]) == 1
    db_conn.commit()

    db_conn.execute("SET TIME ZONE 'America/New_York'")
    row = db_conn.execute(
        "SELECT icao24, callsign, api_time, time_position, latitude, longitude, "
        "baro_altitude_m, on_ground, squawk, category, dq_flags FROM state_vectors"
    ).fetchone()
    assert row[0] == sv.icao24
    assert row[1] == sv.callsign
    assert row[2] == datetime.fromtimestamp(sv.api_time, tz=timezone.utc)
    assert row[3] == datetime.fromtimestamp(sv.time_position, tz=timezone.utc)
    assert row[4] == pytest.approx(sv.latitude)
    assert row[5] == pytest.approx(sv.longitude)
    assert row[6] == pytest.approx(sv.baro_altitude_m)
    assert row[7] is False
    assert row[8] == "1200"
    assert row[9] == 3
    assert row[10] == ["STALE_POSITION"]


def test_duplicate_vector_ignored(db_conn, make_sv):
    poll = new_poll(db_conn)
    assert db.insert_vectors(db_conn, poll, [stored(make_sv())]) == 1
    assert db.insert_vectors(db_conn, poll, [stored(make_sv())]) == 0
    count = db_conn.execute("SELECT count(*) FROM state_vectors").fetchone()[0]
    assert count == 1


@pytest.mark.parametrize(
    "column, value",
    [("icao24", "ZZZZZZ"), ("flight_phase", "TAXI"), ("dq_flags", ["NOT_A_FLAG"]),
     ("latitude", 91.0)],
)
def test_schema_constraints_reject_bad_values(db_conn, make_sv, column, value):
    poll = new_poll(db_conn)
    db.insert_vectors(db_conn, poll, [stored(make_sv())])
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(f"UPDATE state_vectors SET {column} = %s", (value,))


def test_poll_lifecycle_recorded(db_conn):
    poll = new_poll(db_conn)
    status = db_conn.execute("SELECT status FROM poll_runs WHERE id = %s", (poll,)).fetchone()[0]
    assert status == "running"

    db.finish_poll(db_conn, poll, db.PollUpdate(
        "ok", http_status=200, api_time=T, n_states=5, n_inserted=5, n_rejected=0,
        n_flagged=1, credits_remaining=398, duration_ms=850))
    row = db_conn.execute(
        "SELECT status, http_status, api_time, n_states, credits_remaining, finished_at "
        "FROM poll_runs WHERE id = %s", (poll,)
    ).fetchone()
    assert row[:2] == ("ok", 200)
    assert row[2] == NOW
    assert row[3:5] == (5, 398)
    assert row[5] is not None


def test_previous_fixes_returns_latest_non_jump_fix(db_conn, make_sv):
    poll = new_poll(db_conn)
    db.insert_vectors(db_conn, poll, [
        stored(make_sv(api_time=T - 600, time_position=T - 600, latitude=39.10)),
        stored(make_sv(api_time=T - 300, time_position=T - 300, latitude=39.20)),
        stored(make_sv(api_time=T - 100, time_position=T - 100, latitude=10.0), [IMPOSSIBLE_JUMP]),
        stored(make_sv(api_time=T - 3600, time_position=T - 3600, icao24="ffffff")),  # too old
    ])
    fixes = db.previous_fixes(db_conn, ["a1b2c3", "ffffff", "000000"], T)
    assert set(fixes) == {"a1b2c3"}
    assert fixes["a1b2c3"].latitude == pytest.approx(39.20)
    assert fixes["a1b2c3"].time_position == T - 300


def test_purge_removes_old_polls_and_their_vectors(db_conn, make_sv):
    old = new_poll(db_conn, NOW - timedelta(days=40))
    recent = new_poll(db_conn, NOW - timedelta(days=1))
    db.insert_vectors(db_conn, old, [stored(make_sv(api_time=T - 1000))])
    db.insert_vectors(db_conn, recent, [stored(make_sv())])

    assert db.purge_older_than(db_conn, 30, NOW) == 1
    polls = [r[0] for r in db_conn.execute("SELECT id FROM poll_runs").fetchall()]
    assert polls == [recent]
    assert db_conn.execute("SELECT count(*) FROM state_vectors").fetchone()[0] == 1


def test_ingest_lock_is_exclusive(db_conn):
    other = psycopg.connect(db_conn.info.dsn, password=db_conn.info.password)
    try:
        assert db.try_ingest_lock(db_conn)
        assert not db.try_ingest_lock(other)
        db.release_ingest_lock(db_conn)
        assert db.try_ingest_lock(other)
        db.release_ingest_lock(other)
    finally:
        other.close()
