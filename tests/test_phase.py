import pytest

from fda.phase import (
    CLIMB,
    CRUISE,
    DESCENT,
    GROUND,
    LEVEL,
    UNKNOWN,
    altitude_band,
    classify_phase,
)

FT = 1 / 3.28084


@pytest.mark.parametrize(
    "on_ground, alt_m, vr, expected",
    [
        (True, None, None, GROUND),
        (True, 100.0, 5.0, GROUND),  # on_ground wins over noisy altitude
        (False, None, 3.0, UNKNOWN),
        (False, 1000.0, 2.54, CLIMB),
        (False, 1000.0, 2.53, LEVEL),
        (False, 1000.0, -2.54, DESCENT),
        (False, 1000.0, None, LEVEL),
        (False, 20_000 * FT, 0.0, CRUISE),
        (False, 19_900 * FT, 0.0, LEVEL),
        (False, 35_000 * FT, -10.0, DESCENT),
    ],
)
def test_classify_phase(on_ground, alt_m, vr, expected):
    assert classify_phase(on_ground, alt_m, vr) == expected


@pytest.mark.parametrize(
    "on_ground, alt_ft, expected",
    [
        (True, None, "SURFACE"),
        (False, None, "UNKNOWN"),
        (False, -100, "BELOW_3000FT"),
        (False, 2_999, "BELOW_3000FT"),
        (False, 3_000, "3000_9999FT"),
        (False, 10_000, "10000_17999FT"),
        (False, 18_000, "18000_28999FT"),
        (False, 29_000, "FL290_PLUS"),
    ],
)
def test_altitude_band(on_ground, alt_ft, expected):
    alt_m = None if alt_ft is None else (alt_ft + 0.01) * FT
    assert altitude_band(on_ground, alt_m) == expected
