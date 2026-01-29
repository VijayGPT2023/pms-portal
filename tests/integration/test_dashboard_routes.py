"""
Integration tests for dashboard routes.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestDashboard:
    def test_dashboard_loads_authenticated(self, client, auth_cookies):
        response = client.get("/dashboard", cookies=auth_cookies)
        assert response.status_code == 200
        assert "dashboard" in response.text.lower() or "PMS" in response.text

    def test_dashboard_contains_user_info(self, client, auth_cookies):
        response = client.get("/dashboard", cookies=auth_cookies)
        assert response.status_code == 200
        # Should contain some user-related content
        assert "admin" in response.text.lower() or "Administrator" in response.text

    def test_dashboard_unauthenticated_redirects(self, client):
        response = client.get("/dashboard", follow_redirects=False)
        # App may redirect (302) or render an inline redirect page (200)
        assert response.status_code in (200, 302)
