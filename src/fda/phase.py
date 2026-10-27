"""Phase-of-flight and altitude-band classification (REQ-031, ICD section 3.3).

Deliberately simple rules from on_ground, barometric altitude and vertical rate; good
enough for terminal-area traffic statistics, not for per-flight event detection.
"""

from __future__ import annotations

FT_PER_M = 3.28084

GROUND = "GROUND"
CLIMB = "CLIMB"
DESCENT = "DESCENT"
CRUISE = "CRUISE"
LEVEL = "LEVEL"
UNKNOWN = "UNKNOWN"
PHASES = (GROUND, CLIMB, DESCENT, CRUISE, LEVEL, UNKNOWN)

# +/-500 ft/min, the usual threshold between level flight and a climb or descent.
VERTICAL_RATE_THRESHOLD_MPS = 2.54
# FL200; level flight at or above this is treated as en-route cruise.
CRUISE_FLOOR_M = 20_000 / FT_PER_M

ALTITUDE_BANDS = (
    "SURFACE",
    "BELOW_3000FT",
    "3000_9999FT",
    "10000_17999FT",
    "18000_28999FT",
    "FL290_PLUS",
    "UNKNOWN",
)


def classify_phase(
    on_ground: bool, baro_altitude_m: float | None, vertical_rate_mps: float | None
) -> str:
    if on_ground:
        return GROUND
    if baro_altitude_m is None:
        return UNKNOWN
    if vertical_rate_mps is not None:
        if vertical_rate_mps >= VERTICAL_RATE_THRESHOLD_MPS:
            return CLIMB
        if vertical_rate_mps <= -VERTICAL_RATE_THRESHOLD_MPS:
            return DESCENT
    if baro_altitude_m >= CRUISE_FLOOR_M:
        return CRUISE
    return LEVEL


def altitude_band(on_ground: bool, baro_altitude_m: float | None) -> str:
    if on_ground:
        return "SURFACE"
    if baro_altitude_m is None:
        return "UNKNOWN"
    ft = baro_altitude_m * FT_PER_M
    if ft < 3_000:
        return "BELOW_3000FT"
    if ft < 10_000:
        return "3000_9999FT"
    if ft < 18_000:
        return "10000_17999FT"
    if ft < 29_000:
        return "18000_28999FT"
    return "FL290_PLUS"
