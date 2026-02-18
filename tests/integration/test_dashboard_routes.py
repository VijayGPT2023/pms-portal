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


class TestDashboardRedesign:
    """Tests for the 4-tab dashboard redesign."""

    def test_default_mis_tab_loads(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=default_mis", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Default MIS" in response.text

    def test_physical_progress_tab_loads(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=physical_progress", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Physical Progress" in response.text

    def test_financial_progress_tab_loads(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=financial_progress", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Financial Progress" in response.text

    def test_business_mis_tab_loads(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=business_mis", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Business MIS" in response.text

    def test_business_mis_proposals_sub_section(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=business_mis&sub_section=proposals", cookies=auth_cookies)
        assert response.status_code == 200

    def test_business_mis_work_in_hand_sub_section(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=business_mis&sub_section=work_in_hand", cookies=auth_cookies)
        assert response.status_code == 200

    def test_old_tab_assignments_maps_to_default_mis(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=assignments", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Default MIS" in response.text

    def test_old_tab_training_maps_to_default_mis(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=training", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Default MIS" in response.text

    def test_default_tab_is_default_mis(self, client, auth_cookies):
        response = client.get("/dashboard", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Default MIS" in response.text

    def test_business_mis_api_endpoint(self, client, auth_cookies):
        response = client.get("/dashboard/api/business-mis?sub_section=proposals", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "rows" in data or "summary" in data

    def test_default_mis_with_fy_selector(self, client, auth_cookies):
        response = client.get("/dashboard?active_tab=default_mis&fy=2025-26", cookies=auth_cookies)
        assert response.status_code == 200

    def test_default_mis_drill_down(self, client, auth_cookies):
        """Tab A should preserve drill-down sub_view functionality."""
        response = client.get("/dashboard?active_tab=default_mis&sub_view=entities", cookies=auth_cookies)
        assert response.status_code == 200
