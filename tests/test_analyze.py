"""Analysis queries checked against a small hand-built dataset with known answers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fda import analyze, db
from fda.phase import altitude_band, classify_phase

pytestmark = pytest.mark.db

BASE = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
SINCE, UNTIL = BASE - timedelta(hours=1), BASE + timedelta(hours=2)


def add_poll(conn, minute, status, vectors=(), make_sv=None):
    started = BASE + timedelta(minutes=minute)
    poll = db.start_poll(conn, "bbox", False, started)
    api_time = int(started.timestamp())
    stored = []
    for overrides, flags in vectors:
        sv = make_sv(api_time=api_time, time_position=api_time, last_contact=api_time, **overrides)
        stored.append(db.StoredVector(
            sv, classify_phase(sv.on_ground, sv.baro_altitude_m, sv.vertical_rate_mps),
            altitude_band(sv.on_ground, sv.baro_altitude_m), flags))
    db.insert_vectors(conn, poll, stored)
    db.finish_poll(conn, poll, db.PollUpdate(
        status, n_states=len(stored) if status == "ok" else None,
        n_rejected=0 if status == "ok" else None, duration_ms=100))


@pytest.fixture
def seeded(db_conn, make_sv):
    aal = ({"icao24": "a00001", "callsign": "AAL100", "baro_altitude_m": 3000.0}, [])
    ga = ({"icao24": "a00002", "callsign": "N123AB", "on_ground": True,
           "baro_altitude_m": None}, [])
    jbu = ({"icao24": "a00003", "callsign": "JBU5", "vertical_rate_mps": 10.0},
           ["STALE_POSITION"])
    aal_nopos = ({"icao24": "a00001", "callsign": "AAL100", "latitude": None,
                  "longitude": None}, ["MISSING_POSITION"])
    add_poll(db_conn, 0, "ok", [aal, ga], make_sv)
    add_poll(db_conn, 5, "ok", [aal, jbu], make_sv)
    add_poll(db_conn, 10, "ok", [], make_sv)
    add_poll(db_conn, 15, "rate_limited")
    add_poll(db_conn, 30, "ok", [aal_nopos], make_sv)
    return db_conn


def run(conn, name):
    r = analyze.run_all(conn, SINCE, UNTIL, tz="UTC", interval_s=300, names=[name])[0]
    return [dict(zip(r.columns, row, strict=True)) for row in r.rows]


def test_all_analyses_discovered():
    assert analyze.analysis_names() == sorted(analyze.TITLES)


def test_poll_summary(seeded):
    rows = {r["status"]: r for r in run(seeded, "01_poll_summary")}
    assert rows["ok"]["polls"] == 4
    assert rows["ok"]["polls_with_zero_aircraft"] == 1
    assert rows["rate_limited"]["polls"] == 1
    assert rows["ok"]["pct_of_polls"] == Decimal("80.0")


def test_traffic_by_hour_of_day(seeded):
    (row,) = run(seeded, "02_traffic_by_hour_of_day")
    assert row["hour_local"] == 12
    assert row["polls"] == 4
    assert row["avg_aircraft_in_view"] == Decimal("1.3")  # (2 + 2 + 0 + 1) / 4
    assert row["peak_aircraft_in_view"] == 2


def test_hourly_traffic(seeded):
    (row,) = run(seeded, "03_hourly_traffic")
    assert row["hour_start_local"] == datetime(2026, 10, 20, 12, 0)
    assert (row["distinct_aircraft"], row["observations"], row["on_ground_obs"]) == (3, 5, 1)


def test_hourly_traffic_uses_local_time(seeded):
    r = analyze.run_all(seeded, SINCE, UNTIL, tz="America/New_York", names=["03_hourly_traffic"])
    assert r[0].rows[0][0] == datetime(2026, 10, 20, 8, 0)  # EDT is UTC-4


def test_altitude_phase(seeded):
    rows = {(r["altitude_band"], r["flight_phase"]): r["observations"]
            for r in run(seeded, "04_altitude_phase")}
    # Default test altitude is 3000 m (~9,840 ft).
    assert rows == {
        ("SURFACE", "GROUND"): 1,
        ("3000_9999FT", "CLIMB"): 1,
        ("3000_9999FT", "LEVEL"): 3,
    }


def test_altitude_phase_ordering_and_percentages(seeded):
    rows = run(seeded, "04_altitude_phase")
    assert rows[0]["altitude_band"] == "SURFACE"
    assert sum(r["pct_of_obs"] for r in rows) == Decimal("100.0")


def test_data_quality(seeded):
    rows = {r["flag"]: (r["observations"], r["pct_of_obs"]) for r in run(seeded, "05_data_quality")}
    assert rows == {
        "CLEAN (no flags)": (3, Decimal("60.00")),
        "MISSING_POSITION": (1, Decimal("20.00")),
        "STALE_POSITION": (1, Decimal("20.00")),
    }


def test_coverage_gaps(seeded):
    rows = run(seeded, "06_coverage_gaps")
    assert len(rows) == 1
    assert rows[0]["gap_start_local"] == datetime(2026, 10, 20, 12, 10)
    assert rows[0]["gap_end_local"] == datetime(2026, 10, 20, 12, 30)
    assert rows[0]["gap_minutes"] == Decimal("20.0")


def test_operators(seeded):
    rows = {r["operator"]: (r["distinct_aircraft"], r["observations"])
            for r in run(seeded, "07_operators")}
    assert rows == {"AAL": (1, 3), "JBU": (1, 1), "N-number (GA/private)": (1, 1)}


def test_empty_window_returns_no_rows(seeded):
    far = BASE + timedelta(days=10)
    results = analyze.run_all(seeded, far, far + timedelta(hours=1), tz="UTC")
    assert all(r.rows == [] for r in results if r.name != "05_data_quality")


def test_markdown_report(seeded):
    results = analyze.run_all(seeded, SINCE, UNTIL, tz="UTC")
    md = analyze.render_markdown(results, SINCE, UNTIL, "UTC")
    assert md.startswith("# Flight Data Analyzer report")
    for title in analyze.TITLES.values():
        assert f"## {title}" in md
    assert "| status | polls |" in md
    assert "| STALE_POSITION | 1 | 20.00 |" in md
