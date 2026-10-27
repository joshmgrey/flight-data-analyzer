"""Database side of the health check (REQ-042); scripts/healthcheck.sh calls this.

Exit codes: 0 healthy, 1 no successful poll within --max-age-min, 2 database unreachable.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from fda import db
from fda.config import ConfigError, load_settings


@dataclass(frozen=True)
class Freshness:
    last_ok: datetime | None
    last_status: str | None
    age_min: float | None
    healthy: bool


def check_freshness(
    conn: psycopg.Connection, max_age_min: float, now: datetime | None = None
) -> Freshness:
    now = now or datetime.now(timezone.utc)
    last_ok, last_status = conn.execute(
        """
        SELECT (SELECT max(started_at) FROM poll_runs WHERE status = 'ok'),
               (SELECT status FROM poll_runs ORDER BY started_at DESC LIMIT 1)
        """
    ).fetchone()
    if last_ok is None:
        return Freshness(None, last_status, None, False)
    age_min = (now - last_ok).total_seconds() / 60
    return Freshness(last_ok, last_status, age_min, age_min <= max_age_min)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fda.health")
    parser.add_argument("--max-age-min", type=float, default=15)
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        with db.connect(settings.database_url) as conn:
            f = check_freshness(conn, args.max_age_min)
    except (ConfigError, psycopg.Error) as exc:
        print(f"database unreachable: {exc}")
        return 2

    if f.last_ok is None:
        print(f"no successful poll recorded (last status: {f.last_status})")
        return 1
    last_ok = f.last_ok.astimezone(timezone.utc)
    print(
        f"last ok poll {last_ok:%Y-%m-%dT%H:%M:%SZ} ({f.age_min:.1f} min ago); "
        f"last status: {f.last_status}"
    )
    return 0 if f.healthy else 1


if __name__ == "__main__":
    sys.exit(main())
