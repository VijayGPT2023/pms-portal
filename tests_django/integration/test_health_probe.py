"""
F.4 — extended health probe tests (M0-REL-09).
"""
import json
import pytest
from django.test import Client as TestClient


pytestmark = pytest.mark.django_db


class TestHealthProbe:
    URL = "/health/"

    def test_returns_json_with_checks_array(self, db):
        r = TestClient().get(self.URL)
        assert r["Content-Type"].startswith("application/json")
        data = json.loads(r.content)
        assert "status" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) >= 4  # at least DB + migrations + disk + log + backup

    def test_each_check_has_name_severity_detail(self, db):
        r = TestClient().get(self.URL)
        for c in json.loads(r.content)["checks"]:
            assert {"name", "severity", "detail"}.issubset(c.keys())
            assert c["severity"] in ("ok", "warn", "critical")

    def test_database_check_present(self, db):
        r = TestClient().get(self.URL)
        names = [c["name"] for c in json.loads(r.content)["checks"]]
        assert "database" in names

    def test_overall_status_ok_or_degraded_for_normal_test_run(self, db):
        # In tests we have no LOG_FILE / backups dir, so status will be 'degraded'
        # because of those soft warnings. Critical (HTTP 503) should NOT fire.
        r = TestClient().get(self.URL)
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data["status"] in ("ok", "degraded")

    def test_critical_db_down_returns_503(self, db, monkeypatch):
        from core.views import main as main_views
        # Force the db cursor call to raise
        from django.db import connection

        class _BoomConn:
            def cursor(self):
                raise RuntimeError("simulated outage")
        monkeypatch.setattr("core.views.main.connection",
                            _BoomConn(), raising=False)

        # The view imports `connection` inside function, so we need a different patching path:
        # patch django.db.connection used inside the view.
        # Actually the view does `from django.db import connection` inside the function — so the
        # function sees the live connection at each call. The monkeypatch above doesn't intercept
        # that. Use a different approach: patch the cursor() method on the live connection.
        original_cursor = connection.cursor

        def boom_cursor(*a, **kw):
            raise RuntimeError("simulated outage")
        monkeypatch.setattr(connection, "cursor", boom_cursor)

        r = TestClient().get(self.URL)
        assert r.status_code == 503
        data = json.loads(r.content)
        assert data["status"] == "down"
        # restore
        monkeypatch.setattr(connection, "cursor", original_cursor)

    def test_disk_check_reports_usage(self, db):
        r = TestClient().get(self.URL)
        disk = next(c for c in json.loads(r.content)["checks"] if c["name"] == "disk")
        assert "% used" in disk["detail"] or "could not stat" in disk["detail"]

    def test_backup_check_present(self, db):
        r = TestClient().get(self.URL)
        names = [c["name"] for c in json.loads(r.content)["checks"]]
        assert "backup" in names
