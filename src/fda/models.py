"""OpenSky state vector model and parsing of raw `/states/all` rows (ICD section 2.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

ICAO24_RE = re.compile(r"^[0-9a-f]{6}$")

# Positions in each state array, per the OpenSky REST API documentation.
IDX_ICAO24 = 0
IDX_CALLSIGN = 1
IDX_ORIGIN_COUNTRY = 2
IDX_TIME_POSITION = 3
IDX_LAST_CONTACT = 4
IDX_LONGITUDE = 5
IDX_LATITUDE = 6
IDX_BARO_ALTITUDE = 7
IDX_ON_GROUND = 8
IDX_VELOCITY = 9
IDX_TRUE_TRACK = 10
IDX_VERTICAL_RATE = 11
IDX_SENSORS = 12
IDX_GEO_ALTITUDE = 13
IDX_SQUAWK = 14
IDX_SPI = 15
IDX_POSITION_SOURCE = 16
IDX_CATEGORY = 17  # only present with extended=1
MIN_ROW_LENGTH = 17


def utc(epoch_s: int | None) -> datetime | None:
    if epoch_s is None:
        return None
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc)


@dataclass(frozen=True)
class StateVector:
    api_time: int
    icao24: str
    callsign: str | None
    origin_country: str | None
    time_position: int | None
    last_contact: int
    longitude: float | None
    latitude: float | None
    baro_altitude_m: float | None
    on_ground: bool
    velocity_mps: float | None
    true_track_deg: float | None
    vertical_rate_mps: float | None
    geo_altitude_m: float | None
    squawk: str | None
    spi: bool | None
    position_source: int | None
    category: int | None

    @property
    def has_position(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class RejectedRow(ValueError):
    """A raw row that cannot be stored at all (REQ-020)."""


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RejectedRow(f"expected number, got {value!r}")
    return float(value)


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RejectedRow(f"expected integer, got {value!r}")
    return value


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_row(row: Any, api_time: int) -> StateVector:
    """Convert one raw state array into a StateVector, or raise RejectedRow."""
    if not isinstance(row, list) or len(row) < MIN_ROW_LENGTH:
        raise RejectedRow("row is not an array of at least 17 fields")

    icao24 = row[IDX_ICAO24]
    if not isinstance(icao24, str) or not ICAO24_RE.match(icao24.strip().lower()):
        raise RejectedRow(f"invalid icao24 {icao24!r}")

    last_contact = _opt_int(row[IDX_LAST_CONTACT])
    if last_contact is None:
        raise RejectedRow("missing last_contact")

    return StateVector(
        api_time=api_time,
        icao24=icao24.strip().lower(),
        callsign=_opt_str(row[IDX_CALLSIGN]),
        origin_country=_opt_str(row[IDX_ORIGIN_COUNTRY]),
        time_position=_opt_int(row[IDX_TIME_POSITION]),
        last_contact=last_contact,
        longitude=_opt_float(row[IDX_LONGITUDE]),
        latitude=_opt_float(row[IDX_LATITUDE]),
        baro_altitude_m=_opt_float(row[IDX_BARO_ALTITUDE]),
        on_ground=bool(row[IDX_ON_GROUND]),
        velocity_mps=_opt_float(row[IDX_VELOCITY]),
        true_track_deg=_opt_float(row[IDX_TRUE_TRACK]),
        vertical_rate_mps=_opt_float(row[IDX_VERTICAL_RATE]),
        geo_altitude_m=_opt_float(row[IDX_GEO_ALTITUDE]),
        squawk=_opt_str(row[IDX_SQUAWK]),
        spi=None if row[IDX_SPI] is None else bool(row[IDX_SPI]),
        position_source=_opt_int(row[IDX_POSITION_SOURCE]),
        category=_opt_int(row[IDX_CATEGORY]) if len(row) > IDX_CATEGORY else None,
    )


def parse_states(rows: list[Any], api_time: int) -> tuple[list[StateVector], list[str]]:
    """Parse every row; return accepted vectors and a reason for each rejected row."""
    accepted: list[StateVector] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for row in rows:
        try:
            sv = parse_row(row, api_time)
        except RejectedRow as exc:
            rejected.append(str(exc))
            continue
        if sv.icao24 in seen:
            rejected.append(f"duplicate icao24 {sv.icao24} in one response")
            continue
        seen.add(sv.icao24)
        accepted.append(sv)
    return accepted, rejected
