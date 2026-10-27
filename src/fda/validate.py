"""Data-quality rules applied to each accepted state vector (REQ-021..REQ-025).

Flagged records are still stored; the flags travel with them in `state_vectors.dq_flags`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fda.config import BoundingBox
from fda.models import StateVector

MISSING_POSITION = "MISSING_POSITION"
OUTSIDE_BBOX = "OUTSIDE_BBOX"
STALE_POSITION = "STALE_POSITION"
IMPLAUSIBLE_ALTITUDE = "IMPLAUSIBLE_ALTITUDE"
IMPLAUSIBLE_SPEED = "IMPLAUSIBLE_SPEED"
IMPOSSIBLE_JUMP = "IMPOSSIBLE_JUMP"

ALL_FLAGS = (
    MISSING_POSITION,
    OUTSIDE_BBOX,
    STALE_POSITION,
    IMPLAUSIBLE_ALTITUDE,
    IMPLAUSIBLE_SPEED,
    IMPOSSIBLE_JUMP,
)

# Barometric altitude can read slightly negative near sea level on high-pressure days,
# so the floor allows -300 m. 18,300 m (~60,000 ft) is above any civil service ceiling.
MIN_ALTITUDE_M = -300.0
MAX_ALTITUDE_M = 18_300.0
# ~680 kt; faster than any civil aircraft's ground speed in this airspace.
MAX_SPEED_MPS = 350.0
# Implied ground speed between consecutive fixes; looser than MAX_SPEED_MPS to absorb
# position rounding and timestamp jitter.
MAX_JUMP_SPEED_MPS = 400.0
JUMP_WINDOW_S = 30 * 60

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class PrevFix:
    latitude: float
    longitude: float
    time_position: int


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def check_record(sv: StateVector, bbox: BoundingBox, stale_position_s: int = 60) -> list[str]:
    """Single-record rules that need no history."""
    flags: list[str] = []
    if not sv.has_position:
        flags.append(MISSING_POSITION)
    elif not bbox.contains(sv.latitude, sv.longitude):
        flags.append(OUTSIDE_BBOX)

    if sv.time_position is not None and sv.api_time - sv.time_position > stale_position_s:
        flags.append(STALE_POSITION)

    if sv.baro_altitude_m is not None and not (
        MIN_ALTITUDE_M <= sv.baro_altitude_m <= MAX_ALTITUDE_M
    ):
        flags.append(IMPLAUSIBLE_ALTITUDE)

    if sv.velocity_mps is not None and (sv.velocity_mps < 0 or sv.velocity_mps > MAX_SPEED_MPS):
        flags.append(IMPLAUSIBLE_SPEED)
    return flags


def implied_speed_mps(prev: PrevFix, sv: StateVector) -> float | None:
    """Ground speed implied by moving from `prev` to `sv`, or None if not comparable."""
    if not sv.has_position or sv.time_position is None:
        return None
    dt = sv.time_position - prev.time_position
    if dt <= 0 or dt > JUMP_WINDOW_S:
        return None
    return haversine_m(prev.latitude, prev.longitude, sv.latitude, sv.longitude) / dt


def is_impossible_jump(prev: PrevFix | None, sv: StateVector) -> bool:
    if prev is None:
        return False
    speed = implied_speed_mps(prev, sv)
    return speed is not None and speed > MAX_JUMP_SPEED_MPS
