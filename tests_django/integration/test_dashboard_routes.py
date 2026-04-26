"""
Integration tests for dashboard routes.
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestDashboard:
    def test_dashboard_requires_auth(self):
        client = TestClient()
        response = client.get("/dashboard/")
        assert response.status_code == 302

    def test_dashboard_loads(self, auth_client):
        response = auth_client.get("/dashboard/")
        assert response.status_code == 200

    def test_dashboard_summary_loads(self, auth_client):
        response = auth_client.get("/dashboard/summary/")
        assert response.status_code == 200


class TestHealthCheck:
    def test_health_check_returns_json(self):
        client = TestClient()
        response = client.get("/health/")
        # 200 even when degraded (only HTTP 503 on critical DB outage).
        # Test env has no LOG_FILE and no backups dir → 'degraded' is normal.
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "Django" in data["framework"]
        assert "checks" in data
        db_check = next(c for c in data["checks"] if c["name"] == "database")
        assert db_check["severity"] == "ok"
        assert "connected" in db_check["detail"]
