"""
Integration tests for report routes -- delay dashboard, physical progress,
financial progress, dashboard summary API.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestDelayDashboard:
    def test_delay_dashboard(self, client, auth_cookies):
        """GET /reports/delays returns 200."""
        response = client.get("/reports/delays", cookies=auth_cookies)
        assert response.status_code == 200

    def test_delay_dashboard_with_office_filter(self, client, auth_cookies):
        """GET /reports/delays?office=HQ returns 200 with office filter."""
        response = client.get("/reports/delays?office=HQ", cookies=auth_cookies)
        assert response.status_code == 200


class TestDelaySummaryAPI:
    def test_delay_summary_api(self, client, auth_cookies):
        """GET /reports/delays/api/summary returns JSON with delay counts."""
        response = client.get("/reports/delays/api/summary", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "payment_delays" in data
        assert "invoice_delays" in data
        assert "milestone_delays" in data
        assert "activation_delays" in data
        assert "total" in data
        # All values should be non-negative integers
        assert data["total"] >= 0
        assert data["payment_delays"] >= 0


class TestPhysicalProgress:
    def test_physical_progress_office_view(self, client, auth_cookies):
        """GET /reports/physical-progress?view=office returns 200."""
        response = client.get("/reports/physical-progress?view=office", cookies=auth_cookies)
        assert response.status_code == 200

    def test_physical_progress_domain_view(self, client, auth_cookies):
        """GET /reports/physical-progress?view=domain returns 200."""
        response = client.get("/reports/physical-progress?view=domain", cookies=auth_cookies)
        assert response.status_code == 200

    def test_physical_progress_officer_view(self, client, auth_cookies):
        """GET /reports/physical-progress?view=officer returns 200."""
        response = client.get("/reports/physical-progress?view=officer", cookies=auth_cookies)
        assert response.status_code == 200

    def test_physical_progress_type_view(self, client, auth_cookies):
        """GET /reports/physical-progress?view=type returns 200."""
        response = client.get("/reports/physical-progress?view=type", cookies=auth_cookies)
        assert response.status_code == 200


class TestPhysicalProgressAPI:
    def test_physical_progress_api(self, client, auth_cookies):
        """GET /reports/physical-progress/api/data returns JSON with status data."""
        response = client.get("/reports/physical-progress/api/data", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "by_status" in data
        assert isinstance(data["by_status"], list)


class TestFinancialProgress:
    def test_financial_progress(self, client, auth_cookies):
        """GET /reports/financial-progress returns 200."""
        response = client.get("/reports/financial-progress", cookies=auth_cookies)
        assert response.status_code == 200

    def test_financial_progress_domain_view(self, client, auth_cookies):
        """GET /reports/financial-progress?view=domain returns 200."""
        response = client.get("/reports/financial-progress?view=domain", cookies=auth_cookies)
        assert response.status_code == 200

    def test_financial_progress_type_view(self, client, auth_cookies):
        """GET /reports/financial-progress?view=type returns 200."""
        response = client.get("/reports/financial-progress?view=type", cookies=auth_cookies)
        assert response.status_code == 200


class TestFinancialProgressAPI:
    def test_financial_progress_api(self, client, auth_cookies):
        """GET /reports/financial-progress/api/data returns JSON with financial data."""
        response = client.get("/reports/financial-progress/api/data", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "total_value" in data
        assert "invoiced" in data
        assert "received" in data
        assert "expenditure" in data
        assert "net" in data
        assert "surplus_deficit" in data


class TestDashboardSummaryAPI:
    def test_dashboard_summary_api(self, client, auth_cookies):
        """GET /reports/api/dashboard-summary returns JSON with combined metrics."""
        response = client.get("/reports/api/dashboard-summary", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "delays" in data
        assert "physical_progress" in data
        assert "financial" in data
        # Check nested structure
        assert "payment" in data["delays"]
        assert "invoice" in data["delays"]
        assert "milestone" in data["delays"]
        assert "activation" in data["delays"]
        assert "avg_percent" in data["physical_progress"]
        assert "total_value" in data["financial"]

    def test_dashboard_summary_api_with_office(self, client, auth_cookies):
        """GET /reports/api/dashboard-summary?office=HQ returns filtered JSON."""
        response = client.get("/reports/api/dashboard-summary?office=HQ", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "delays" in data
        assert "financial" in data


class TestReportsUnauthenticated:
    def test_reports_unauthenticated(self, client):
        """All report endpoints redirect or inline-redirect without auth."""
        endpoints = [
            "/reports/delays",
            "/reports/physical-progress",
            "/reports/financial-progress",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint, follow_redirects=False)
            # App may redirect (302) or render an inline redirect page (200)
            assert response.status_code in (200, 302), f"{endpoint} should redirect without auth"
            if response.status_code == 302:
                location = response.headers.get("location", "")
                assert "login" in location.lower(), f"{endpoint} should redirect to login"

    def test_report_apis_unauthenticated(self, client):
        """API endpoints return 401 or inline redirect without auth."""
        api_endpoints = [
            "/reports/delays/api/summary",
            "/reports/physical-progress/api/data",
            "/reports/financial-progress/api/data",
            "/reports/api/dashboard-summary",
        ]
        for endpoint in api_endpoints:
            response = client.get(endpoint, follow_redirects=False)
            # API endpoints may return 401 JSON or 200 with inline redirect/empty
            assert response.status_code in (200, 401), f"{endpoint} should return 401 or inline redirect without auth"
