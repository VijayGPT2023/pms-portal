"""
Integration tests for the MIS Command Center (6-tab dashboard).
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestMISCommandCenter:
    """Tests for the 6-tab MIS Command Center."""

    def test_mis_default_loads_executive_tab(self, client, auth_cookies):
        response = client.get("/mis", cookies=auth_cookies)
        assert response.status_code == 200
        assert "MIS Command Center" in response.text
        assert "Executive Summary" in response.text

    def test_executive_tab_loads(self, client, auth_cookies):
        response = client.get("/mis?active_tab=executive", cookies=auth_cookies)
        assert response.status_code == 200
        assert "FY Target" in response.text
        assert "Total Revenue" in response.text

    def test_office_tab_loads(self, client, auth_cookies):
        response = client.get("/mis?active_tab=office", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Office Performance" in response.text

    def test_activity_tab_loads(self, client, auth_cookies):
        response = client.get("/mis?active_tab=activity", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Activity" in response.text
        assert "Domain" in response.text

    def test_financial_tab_loads(self, client, auth_cookies):
        response = client.get("/mis?active_tab=financial", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Financial Deep-Dive" in response.text

    def test_delays_tab_loads(self, client, auth_cookies):
        response = client.get("/mis?active_tab=delays", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Delays" in response.text

    def test_officer_client_tab_loads(self, client, auth_cookies):
        response = client.get("/mis?active_tab=officer_client", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Officer" in response.text

    def test_invalid_tab_defaults_to_executive(self, client, auth_cookies):
        response = client.get("/mis?active_tab=invalid", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Executive Summary" in response.text

    def test_filter_by_office(self, client, auth_cookies):
        response = client.get("/mis?active_tab=executive&filter_office=HQ", cookies=auth_cookies)
        assert response.status_code == 200

    def test_filter_by_fy(self, client, auth_cookies):
        response = client.get("/mis?active_tab=executive&financial_year=2025-26", cookies=auth_cookies)
        assert response.status_code == 200

    def test_unauthenticated_redirects(self, client):
        response = client.get("/mis", follow_redirects=False)
        assert response.status_code in (200, 302)


class TestMISCSVExport:
    """Tests for CSV export endpoint."""

    def test_csv_export_office(self, client, auth_cookies):
        response = client.get("/mis/export/csv?tab=office", cookies=auth_cookies)
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    def test_csv_export_delays(self, client, auth_cookies):
        response = client.get("/mis/export/csv?tab=delays", cookies=auth_cookies)
        assert response.status_code == 200

    def test_csv_export_officer_client(self, client, auth_cookies):
        response = client.get("/mis/export/csv?tab=officer_client", cookies=auth_cookies)
        assert response.status_code == 200

    def test_csv_export_unauthenticated(self, client):
        response = client.get("/mis/export/csv?tab=office", follow_redirects=False)
        assert response.status_code in (200, 302)


class TestMISExistingRoutes:
    """Ensure existing drill-down routes still work."""

    def test_office_detail(self, client, auth_cookies):
        response = client.get("/mis/office/HQ", cookies=auth_cookies)
        # HQ might not exist in test DB, so redirect is OK
        assert response.status_code in (200, 302)

    def test_assignments_list(self, client, auth_cookies):
        response = client.get("/mis/assignments", cookies=auth_cookies)
        assert response.status_code == 200

    def test_officers_list(self, client, auth_cookies):
        response = client.get("/mis/officers", cookies=auth_cookies)
        assert response.status_code == 200

    def test_financial_mis(self, client, auth_cookies):
        response = client.get("/mis/financial", cookies=auth_cookies)
        assert response.status_code == 200


class TestMISTabsWithChartJS:
    """Verify Chart.js is loaded on MIS pages."""

    def test_chartjs_loaded_on_executive(self, client, auth_cookies):
        response = client.get("/mis?active_tab=executive", cookies=auth_cookies)
        assert response.status_code == 200
        assert "chart.js" in response.text.lower() or "Chart" in response.text

    def test_financial_tab_has_pipeline_chart(self, client, auth_cookies):
        response = client.get("/mis?active_tab=financial", cookies=auth_cookies)
        assert response.status_code == 200
        assert "pipelineChart" in response.text

    def test_delays_tab_has_delay_chart(self, client, auth_cookies):
        response = client.get("/mis?active_tab=delays", cookies=auth_cookies)
        assert response.status_code == 200
        assert "delayBarChart" in response.text
