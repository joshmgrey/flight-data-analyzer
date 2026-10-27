"""Runtime configuration, read from environment variables (see deploy/fda.env.example)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# OpenSky rate-limit floors (REQ-002). Anonymous users get 400 API credits/day and a
# 1-credit query every 300 s uses 288/day; registered users get 4000/day.
ANON_MIN_INTERVAL_S = 300
AUTH_MIN_INTERVAL_S = 60


class ConfigError(ValueError):
    """Raised when the environment does not describe a valid configuration."""


@dataclass(frozen=True)
class BoundingBox:
    lamin: float
    lomin: float
    lamax: float
    lomax: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lamin < self.lamax <= 90):
            raise ConfigError(f"invalid latitude range {self.lamin}..{self.lamax}")
        if not (-180 <= self.lomin < self.lomax <= 180):
            raise ConfigError(f"invalid longitude range {self.lomin}..{self.lomax}")
        # Boxes over 25 square degrees cost more than 1 OpenSky credit per call.
        if (self.lamax - self.lamin) * (self.lomax - self.lomin) > 25:
            raise ConfigError("bounding box larger than 25 square degrees")

    @classmethod
    def parse(cls, text: str) -> BoundingBox:
        try:
            lamin, lomin, lamax, lomax = (float(p) for p in text.split(","))
        except ValueError as exc:
            raise ConfigError(f"FDA_BBOX must be 'lamin,lomin,lamax,lomax', got {text!r}") from exc
        return cls(lamin, lomin, lamax, lomax)

    def as_params(self) -> dict[str, float]:
        return {"lamin": self.lamin, "lomin": self.lomin, "lamax": self.lamax, "lomax": self.lomax}

    def contains(self, lat: float, lon: float) -> bool:
        return self.lamin <= lat <= self.lamax and self.lomin <= lon <= self.lomax

    def __str__(self) -> str:
        return f"{self.lamin},{self.lomin},{self.lamax},{self.lomax}"


# Roughly 45 km around Atlantic City International Airport (ACY, 39.4576 N 74.5772 W),
# home of the FAA William J. Hughes Technical Center. The western edge stops short of
# PHL so Philadelphia ground traffic does not swamp the sample.
ACY_BBOX = BoundingBox(lamin=39.05, lomin=-75.05, lamax=39.85, lomax=-74.10)


@dataclass(frozen=True)
class Settings:
    database_url: str
    bbox: BoundingBox = ACY_BBOX
    client_id: str | None = None
    client_secret: str | None = None
    poll_interval_s: int = ANON_MIN_INTERVAL_S
    retention_days: int = 30
    stale_position_s: int = 60
    log_level: str = "INFO"

    @property
    def authenticated(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def min_interval_s(self) -> int:
        return AUTH_MIN_INTERVAL_S if self.authenticated else ANON_MIN_INTERVAL_S


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    database_url = env.get("DATABASE_URL")
    if not database_url:
        raise ConfigError("DATABASE_URL is not set")

    bbox = BoundingBox.parse(env["FDA_BBOX"]) if env.get("FDA_BBOX") else ACY_BBOX
    settings = Settings(
        database_url=database_url,
        bbox=bbox,
        client_id=env.get("OPENSKY_CLIENT_ID") or None,
        client_secret=env.get("OPENSKY_CLIENT_SECRET") or None,
        poll_interval_s=_int(env, "FDA_POLL_INTERVAL_S", ANON_MIN_INTERVAL_S),
        retention_days=_int(env, "FDA_RETENTION_DAYS", 30),
        stale_position_s=_int(env, "FDA_STALE_POSITION_S", 60),
        log_level=env.get("FDA_LOG_LEVEL", "INFO").upper(),
    )
    if settings.poll_interval_s < settings.min_interval_s:
        mode = "authenticated" if settings.authenticated else "anonymous"
        raise ConfigError(
            f"FDA_POLL_INTERVAL_S={settings.poll_interval_s} is below the {mode} "
            f"OpenSky floor of {settings.min_interval_s} s"
        )
    if settings.retention_days < 1:
        raise ConfigError("FDA_RETENTION_DAYS must be at least 1")
    return settings
