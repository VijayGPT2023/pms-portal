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
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"
        assert "Django" in data["framework"]
