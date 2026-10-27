"""PostgreSQL access: schema setup, poll bookkeeping and state-vector storage."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import resources

import psycopg

from fda.models import StateVector, utc
from fda.validate import IMPOSSIBLE_JUMP, JUMP_WINDOW_S, PrevFix

# Arbitrary constant key for pg_try_advisory_lock so two ingest runs never overlap.
INGEST_LOCK_KEY = 4_175_309


def schema_sql() -> str:
    return resources.files("fda").joinpath("sql/schema.sql").read_text(encoding="utf-8")


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, connect_timeout=10)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(schema_sql())
    conn.commit()


def try_ingest_lock(conn: psycopg.Connection) -> bool:
    row = conn.execute("SELECT pg_try_advisory_lock(%s)", (INGEST_LOCK_KEY,)).fetchone()
    return bool(row[0])


def release_ingest_lock(conn: psycopg.Connection) -> None:
    conn.execute("SELECT pg_advisory_unlock(%s)", (INGEST_LOCK_KEY,))


def last_attempt_started_at(conn: psycopg.Connection) -> datetime | None:
    row = conn.execute("SELECT max(started_at) FROM poll_runs").fetchone()
    return row[0]


def start_poll(
    conn: psycopg.Connection, bbox: str, authenticated: bool, started_at: datetime
) -> int:
    row = conn.execute(
        """
        INSERT INTO poll_runs (started_at, status, bbox, authenticated)
        VALUES (%s, 'running', %s, %s) RETURNING id
        """,
        (started_at, bbox, authenticated),
    ).fetchone()
    conn.commit()
    return row[0]


@dataclass
class PollUpdate:
    status: str
    http_status: int | None = None
    api_time: int | None = None
    n_states: int | None = None
    n_inserted: int | None = None
    n_rejected: int | None = None
    n_flagged: int | None = None
    credits_remaining: int | None = None
    duration_ms: int | None = None
    error: str | None = None


def finish_poll(conn: psycopg.Connection, poll_id: int, u: PollUpdate) -> None:
    conn.execute(
        """
        UPDATE poll_runs SET
            finished_at = now(), status = %s, http_status = %s, api_time = %s,
            n_states = %s, n_inserted = %s, n_rejected = %s, n_flagged = %s,
            credits_remaining = %s, duration_ms = %s, error = %s
        WHERE id = %s
        """,
        (
            u.status, u.http_status, utc(u.api_time), u.n_states, u.n_inserted,
            u.n_rejected, u.n_flagged, u.credits_remaining, u.duration_ms, u.error, poll_id,
        ),
    )
    conn.commit()


def previous_fixes(
    conn: psycopg.Connection, icao24s: list[str], before_api_time: int
) -> dict[str, PrevFix]:
    """Latest stored, non-jump position per aircraft within the jump window."""
    if not icao24s:
        return {}
    before = utc(before_api_time)
    rows = conn.execute(
        """
        SELECT DISTINCT ON (icao24) icao24, latitude, longitude, time_position
        FROM state_vectors
        WHERE icao24 = ANY(%s)
          AND api_time < %s
          AND api_time >= %s
          AND latitude IS NOT NULL AND longitude IS NOT NULL
          AND time_position IS NOT NULL
          AND NOT (%s = ANY(dq_flags))
        ORDER BY icao24, api_time DESC
        """,
        (icao24s, before, before - timedelta(seconds=JUMP_WINDOW_S), IMPOSSIBLE_JUMP),
    ).fetchall()
    return {
        r[0].strip(): PrevFix(r[1], r[2], int(r[3].timestamp())) for r in rows
    }


@dataclass(frozen=True)
class StoredVector:
    sv: StateVector
    flight_phase: str
    altitude_band: str
    dq_flags: list[str]


def insert_vectors(conn: psycopg.Connection, poll_id: int, vectors: list[StoredVector]) -> int:
    """Insert vectors, skipping (icao24, api_time) duplicates (REQ-011). Returns rows inserted."""
    inserted = 0
    with conn.cursor() as cur:
        for v in vectors:
            s = v.sv
            cur.execute(
                """
                INSERT INTO state_vectors (
                    poll_id, api_time, icao24, callsign, origin_country, time_position,
                    last_contact, longitude, latitude, baro_altitude_m, geo_altitude_m,
                    on_ground, velocity_mps, true_track_deg, vertical_rate_mps, squawk, spi,
                    position_source, category, flight_phase, altitude_band, dq_flags
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT state_vectors_icao24_api_time_key DO NOTHING
                """,
                (
                    poll_id, utc(s.api_time), s.icao24, s.callsign, s.origin_country,
                    utc(s.time_position), utc(s.last_contact), s.longitude, s.latitude,
                    s.baro_altitude_m, s.geo_altitude_m, s.on_ground, s.velocity_mps,
                    s.true_track_deg, s.vertical_rate_mps, s.squawk, s.spi, s.position_source,
                    s.category, v.flight_phase, v.altitude_band, v.dq_flags,
                ),
            )
            inserted += cur.rowcount
    return inserted


def purge_older_than(conn: psycopg.Connection, days: int, now: datetime) -> int:
    """Delete polls (and, by cascade, their vectors) older than `days` (REQ-045)."""
    cur = conn.execute(
        "DELETE FROM poll_runs WHERE started_at < %s", (now - timedelta(days=days),)
    )
    return cur.rowcount


def main(argv: list[str] | None = None) -> int:
    from fda.config import load_settings

    parser = argparse.ArgumentParser(prog="python -m fda.db")
    parser.add_argument("command", choices=["init"], help="init: create tables if missing")
    parser.parse_args(argv)
    settings = load_settings()
    with connect(settings.database_url) as conn:
        apply_schema(conn)
    print("schema applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
