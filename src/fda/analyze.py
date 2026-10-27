"""Run the SQL analyses in fda/sql/analyses and print them or write a Markdown report."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

import psycopg

from fda import db
from fda.config import load_settings

TITLES = {
    "01_poll_summary": "Poll outcomes",
    "02_traffic_by_hour_of_day": "Aircraft in view by hour of day",
    "03_hourly_traffic": "Hourly traffic",
    "04_altitude_phase": "Altitude band and phase of flight",
    "05_data_quality": "Data-quality flags",
    "06_coverage_gaps": "Coverage gaps (longest 25)",
    "07_operators": "Operators by callsign",
}


@dataclass(frozen=True)
class Result:
    name: str
    title: str
    columns: list[str]
    rows: list[tuple[Any, ...]]


def analysis_names() -> list[str]:
    folder = resources.files("fda").joinpath("sql/analyses")
    return sorted(p.name.removesuffix(".sql") for p in folder.iterdir() if p.name.endswith(".sql"))


def load_sql(name: str) -> str:
    return resources.files("fda").joinpath(f"sql/analyses/{name}.sql").read_text(encoding="utf-8")


def run_analysis(conn: psycopg.Connection, name: str, params: dict[str, Any]) -> Result:
    cur = conn.execute(load_sql(name), params)
    columns = [d.name for d in cur.description]
    return Result(name, TITLES.get(name, name), columns, cur.fetchall())


def run_all(
    conn: psycopg.Connection,
    since: datetime,
    until: datetime,
    tz: str = "America/New_York",
    interval_s: int = 300,
    names: list[str] | None = None,
) -> list[Result]:
    params = {"since": since, "until": until, "tz": tz, "interval_s": interval_s}
    return [run_analysis(conn, n, params) for n in (names or analysis_names())]


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, Decimal):
        return f"{value:f}"
    return str(value)


def render_markdown(
    results: list[Result], since: datetime, until: datetime, tz: str, max_rows: int = 48
) -> str:
    lines = [
        "# Flight Data Analyzer report",
        "",
        f"Window: {since:%Y-%m-%d %H:%M} to {until:%Y-%m-%d %H:%M} UTC; local times in {tz}.",
        "",
    ]
    for r in results:
        lines += [f"## {r.title}", ""]
        if not r.rows:
            lines += ["_No rows._", ""]
            continue
        lines.append("| " + " | ".join(r.columns) + " |")
        lines.append("|" + "|".join("---" for _ in r.columns) + "|")
        for row in r.rows[:max_rows]:
            lines.append("| " + " | ".join(_fmt(v) for v in row) + " |")
        if len(r.rows) > max_rows:
            lines.append(f"\n_{len(r.rows) - max_rows} more rows not shown._")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fda.analyze", description=__doc__)
    parser.add_argument("--days", type=float, default=7, help="look back this many days (7)")
    parser.add_argument("--tz", default="America/New_York")
    parser.add_argument("--markdown", type=Path, help="write the report to this file")
    parser.add_argument("--only", nargs="*", help="run only these analyses, e.g. 05_data_quality")
    args = parser.parse_args(argv)

    settings = load_settings()
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=args.days)
    with db.connect(settings.database_url) as conn:
        results = run_all(conn, since, until, args.tz, settings.poll_interval_s, args.only)

    report = render_markdown(results, since, until, args.tz)
    if args.markdown:
        args.markdown.write_text(report, encoding="utf-8")
        print(f"wrote {args.markdown}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
