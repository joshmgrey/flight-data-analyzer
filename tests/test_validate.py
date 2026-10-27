"""Data-validation tests for the quality rules in fda.validate (REQ-021..REQ-025)."""

import pytest

from fda.config import ACY_BBOX
from fda.models import parse_states
from fda.validate import (
    IMPLAUSIBLE_ALTITUDE,
    IMPLAUSIBLE_SPEED,
    MISSING_POSITION,
    OUTSIDE_BBOX,
    STALE_POSITION,
    PrevFix,
    check_record,
    haversine_m,
    implied_speed_mps,
    is_impossible_jump,
)
from tests.conftest import SAMPLE_API_TIME

T = SAMPLE_API_TIME


def flags(sv):
    return check_record(sv, ACY_BBOX, stale_position_s=60)


def test_clean_record_has_no_flags(make_sv):
    assert flags(make_sv()) == []


@pytest.mark.parametrize("lat, lon", [(None, -74.5), (39.4, None), (None, None)])
def test_missing_position(make_sv, lat, lon):
    assert MISSING_POSITION in flags(make_sv(latitude=lat, longitude=lon))


def test_outside_bbox(make_sv):
    # PHL is outside the ACY box.
    assert flags(make_sv(latitude=39.8744, longitude=-75.2424)) == [OUTSIDE_BBOX]


@pytest.mark.parametrize("age_s, stale", [(0, False), (60, False), (61, True), (179, True)])
def test_stale_position_threshold(make_sv, age_s, stale):
    result = flags(make_sv(time_position=T - age_s))
    assert (STALE_POSITION in result) is stale


def test_null_time_position_not_stale(make_sv):
    assert STALE_POSITION not in flags(make_sv(time_position=None, latitude=None))


@pytest.mark.parametrize(
    "alt, bad",
    [(-30.48, False), (-300.0, False), (-301.0, True), (18_300.0, False), (20_000.0, True)],
)
def test_implausible_altitude(make_sv, alt, bad):
    assert (IMPLAUSIBLE_ALTITUDE in flags(make_sv(baro_altitude_m=alt))) is bad


@pytest.mark.parametrize("v, bad", [(0.0, False), (350.0, False), (350.1, True), (-1.0, True)])
def test_implausible_speed(make_sv, v, bad):
    assert (IMPLAUSIBLE_SPEED in flags(make_sv(velocity_mps=v))) is bad


def test_multiple_flags_accumulate(make_sv):
    sv = make_sv(time_position=T - 600, baro_altitude_m=25_000.0, velocity_mps=900.0)
    assert set(flags(sv)) == {STALE_POSITION, IMPLAUSIBLE_ALTITUDE, IMPLAUSIBLE_SPEED}


def test_real_sample_flags(sample_body):
    """The captured sample has known stale positions and PHL traffic outside the box."""
    vectors, _ = parse_states(sample_body["states"], sample_body["time"])
    by_icao = {v.icao24: flags(v) for v in vectors}
    # ae649c's last position is 179 s older than the response time.
    assert STALE_POSITION in by_icao["ae649c"]
    # a88075 is on the ground at PHL.
    assert OUTSIDE_BBOX in by_icao["a88075"]
    # -30.48 m baro altitude is a real low-altitude reading, not an error.
    assert IMPLAUSIBLE_ALTITUDE not in by_icao["ae649c"]


def test_haversine_known_distance():
    # ACY to PHL is about 73 km great-circle.
    assert haversine_m(39.4576, -74.5772, 39.8744, -75.2424) == pytest.approx(73_000, rel=0.03)


def test_jump_detected_for_teleport(make_sv):
    prev = PrevFix(39.46, -74.58, T - 10)
    # ~45 km in 10 s is 4,500 m/s.
    sv = make_sv(latitude=39.86, longitude=-74.58, time_position=T)
    assert implied_speed_mps(prev, sv) > 4000
    assert is_impossible_jump(prev, sv)


def test_normal_motion_not_a_jump(make_sv):
    prev = PrevFix(39.46, -74.58, T - 300)
    # ~44 km in 300 s is ~148 m/s, an ordinary jet speed.
    sv = make_sv(latitude=39.46, longitude=-74.07, time_position=T)
    assert not is_impossible_jump(prev, sv)


@pytest.mark.parametrize("prev_t", [T, T + 5, T - 31 * 60])
def test_jump_skipped_when_times_not_comparable(make_sv, prev_t):
    prev = PrevFix(0.0, 0.0, prev_t)
    assert implied_speed_mps(prev, make_sv(time_position=T)) is None
    assert not is_impossible_jump(prev, make_sv(time_position=T))


def test_jump_needs_history(make_sv):
    assert not is_impossible_jump(None, make_sv())
