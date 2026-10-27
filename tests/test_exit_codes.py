"""Process exit codes that systemd and the health check rely on (REQ-044)."""

from fda import health, ingest


def test_exit_codes_are_distinct():
    codes = [ingest.EXIT_OK, ingest.EXIT_CONFIG, ingest.EXIT_RATE_LIMITED,
             ingest.EXIT_UPSTREAM, ingest.EXIT_DB]
    assert len(set(codes)) == len(codes)


def test_ingest_config_error_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert ingest.main([]) == ingest.EXIT_CONFIG


def test_ingest_db_error_when_unreachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert ingest.main([]) == ingest.EXIT_DB


def test_health_reports_unreachable_database(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert health.main([]) == 2
    assert "unreachable" in capsys.readouterr().out
