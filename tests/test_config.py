import pytest

from fda.config import (
    ACY_BBOX,
    ANON_MIN_INTERVAL_S,
    AUTH_MIN_INTERVAL_S,
    BoundingBox,
    ConfigError,
    load_settings,
)

ACY_LAT, ACY_LON = 39.4576, -74.5772
PHL_LAT, PHL_LON = 39.8744, -75.2424


def test_default_bbox_contains_acy_and_excludes_phl():
    s = load_settings({"DATABASE_URL": "postgresql://x"})
    assert s.bbox == ACY_BBOX
    assert s.bbox.contains(ACY_LAT, ACY_LON)
    assert not s.bbox.contains(PHL_LAT, PHL_LON)


def test_bbox_override_parsed():
    s = load_settings({"DATABASE_URL": "postgresql://x", "FDA_BBOX": "39,-75,40,-74"})
    assert s.bbox == BoundingBox(39, -75, 40, -74)


@pytest.mark.parametrize("text", ["1,2,3", "a,b,c,d", "40,-75,39,-74", "0,0,10,10"])
def test_invalid_bbox_rejected(text):
    # "0,0,10,10" is 100 square degrees: more than one OpenSky credit per call.
    with pytest.raises(ConfigError):
        load_settings({"DATABASE_URL": "postgresql://x", "FDA_BBOX": text})


def test_missing_database_url_rejected():
    with pytest.raises(ConfigError):
        load_settings({})


def test_anonymous_interval_floor_enforced():
    with pytest.raises(ConfigError, match="anonymous"):
        load_settings({"DATABASE_URL": "postgresql://x", "FDA_POLL_INTERVAL_S": "60"})


def test_authenticated_interval_floor_is_lower():
    env = {
        "DATABASE_URL": "postgresql://x",
        "OPENSKY_CLIENT_ID": "id",
        "OPENSKY_CLIENT_SECRET": "secret",
        "FDA_POLL_INTERVAL_S": "60",
    }
    s = load_settings(env)
    assert s.authenticated
    assert s.min_interval_s == AUTH_MIN_INTERVAL_S
    with pytest.raises(ConfigError):
        load_settings({**env, "FDA_POLL_INTERVAL_S": "30"})


def test_anonymous_daily_credit_budget_fits():
    # 1 credit per call at the anonymous floor must stay under 400 credits/day.
    assert 86_400 / ANON_MIN_INTERVAL_S <= 400
    assert 86_400 / AUTH_MIN_INTERVAL_S <= 4_000
