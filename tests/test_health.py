from datetime import datetime, timedelta, timezone

import pytest

from fda import db
from fda.health import check_freshness

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def poll(conn, minutes_ago, status):
    pid = db.start_poll(conn, "bbox", False, NOW - timedelta(minutes=minutes_ago))
    db.finish_poll(conn, pid, db.PollUpdate(status))


def test_unhealthy_when_no_polls(db_conn):
    f = check_freshness(db_conn, 15, now=NOW)
    assert not f.healthy and f.last_ok is None


def test_healthy_with_recent_ok_poll(db_conn):
    poll(db_conn, 4, "ok")
    f = check_freshness(db_conn, 15, now=NOW)
    assert f.healthy
    assert f.age_min == pytest.approx(4)


def test_unhealthy_when_only_recent_polls_failed(db_conn):
    poll(db_conn, 30, "ok")
    poll(db_conn, 5, "upstream_error")
    f = check_freshness(db_conn, 15, now=NOW)
    assert not f.healthy
    assert f.last_status == "upstream_error"
    assert f.age_min == pytest.approx(30)
