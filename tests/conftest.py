from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fda.models import StateVector

FIXTURES = Path(__file__).parent / "fixtures"

# 2026-10-27T23:35:03Z, the `time` of the captured sample response.
SAMPLE_API_TIME = 1793144103


@pytest.fixture
def sample_body() -> dict[str, Any]:
    """A real /states/all response captured around ACY/PHL with extended=1."""
    return json.loads((FIXTURES / "opensky_states_sample.json").read_text())


BASE_SV = StateVector(
    api_time=SAMPLE_API_TIME,
    icao24="a1b2c3",
    callsign="JBU123",
    origin_country="United States",
    time_position=SAMPLE_API_TIME - 2,
    last_contact=SAMPLE_API_TIME - 1,
    longitude=-74.58,
    latitude=39.46,
    baro_altitude_m=3000.0,
    on_ground=False,
    velocity_mps=150.0,
    true_track_deg=90.0,
    vertical_rate_mps=0.0,
    geo_altitude_m=3100.0,
    squawk="1200",
    spi=False,
    position_source=0,
    category=3,
)


@pytest.fixture
def make_sv():
    def _make(**overrides: Any) -> StateVector:
        return replace(BASE_SV, **overrides)

    return _make


def raw_row(sv: StateVector) -> list[Any]:
    """Inverse of models.parse_row, for building synthetic API responses."""
    return [
        sv.icao24, sv.callsign, sv.origin_country, sv.time_position, sv.last_contact,
        sv.longitude, sv.latitude, sv.baro_altitude_m, sv.on_ground, sv.velocity_mps,
        sv.true_track_deg, sv.vertical_rate_mps, None, sv.geo_altitude_m, sv.squawk, sv.spi,
        sv.position_source, sv.category,
    ]


class FakeResponse:
    def __init__(self, status_code: int = 200, body: Any = None, headers: dict | None = None,
                 text: str | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self._text = text
        self.headers = headers or {}

    def json(self) -> Any:
        if self._text is not None:
            raise ValueError("not JSON")
        return self._body


class FakeSession:
    """Stands in for requests.Session; each queued item is a FakeResponse or an exception."""

    def __init__(self, gets: list[Any] | None = None, posts: list[Any] | None = None) -> None:
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    def _next(self, queue: list[Any]) -> FakeResponse:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return self._next(self.gets)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        return self._next(self.posts)


@pytest.fixture
def db_conn():
    """A connection whose search_path is a fresh schema, dropped after the test.

    Uses TEST_DATABASE_URL so the suite can never touch the production tables.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    from fda import db

    schema = f"test_{uuid.uuid4().hex[:12]}"
    conn = psycopg.connect(url)
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.commit()
    db.apply_schema(conn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute(f"DROP SCHEMA {schema} CASCADE")
        conn.commit()
        conn.close()
