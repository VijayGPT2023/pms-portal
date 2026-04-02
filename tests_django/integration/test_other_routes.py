"""
Integration tests for remaining routes: clients, training, utilization,
reports, proposals, MIS, admin, profile, non-revenue, change requests.
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestClientRoutes:
    def test_client_list_loads(self, auth_client):
        response = auth_client.get("/clients/")
        assert response.status_code == 200

    def test_new_client_form(self, auth_client):
        response = auth_client.get("/clients/new/")
        assert response.status_code == 200

    def test_client_view(self, auth_client, sample_client):
        response = auth_client.get(f"/clients/{sample_client.id}/view/")
        assert response.status_code == 200

    def test_client_mis(self, auth_client):
        response = auth_client.get("/clients/mis/")
        assert response.status_code == 200


class TestTrainingRoutes:
    def test_training_list_loads(self, auth_client):
        response = auth_client.get("/training/")
        assert response.status_code == 200

    def test_training_create_form(self, auth_client):
        response = auth_client.get("/training/create/")
        assert response.status_code == 200


class TestUtilizationRoutes:
    def test_utilization_list_loads(self, auth_client):
        response = auth_client.get("/utilization/")
        assert response.status_code == 200

    def test_new_claim_form(self, auth_client):
        response = auth_client.get("/utilization/new/")
        assert response.status_code == 200

    def test_utilization_summary(self, auth_client):
        response = auth_client.get("/utilization/summary/")
        assert response.status_code == 200


class TestReportRoutes:
    def test_delay_dashboard(self, auth_client):
        response = auth_client.get("/reports/delays/")
        assert response.status_code == 200

    def test_physical_progress(self, auth_client):
        response = auth_client.get("/reports/physical-progress/")
        assert response.status_code == 200

    def test_financial_progress(self, auth_client):
        response = auth_client.get("/reports/financial-progress/")
        assert response.status_code == 200

    def test_delay_summary_api(self, auth_client):
        response = auth_client.get("/reports/delays/api/summary/")
        assert response.status_code == 200
        assert response.json() is not None


class TestProposalRoutes:
    def test_proposal_list(self, auth_client):
        response = auth_client.get("/proposals/")
        assert response.status_code == 200

    def test_upload_form(self, auth_client, sample_assignment):
        response = auth_client.get(f"/proposals/upload/{sample_assignment.id}/")
        assert response.status_code == 200


class TestMISRoutes:
    def test_mis_dashboard(self, auth_client):
        response = auth_client.get("/mis/")
        assert response.status_code == 200

    def test_mis_csv_export(self, auth_client):
        response = auth_client.get("/mis/export/csv/")
        assert response.status_code == 200


class TestNonRevenueRoutes:
    def test_list_suggestions(self, auth_client):
        response = auth_client.get("/non-revenue/")
        assert response.status_code == 200

    def test_create_form(self, auth_client):
        response = auth_client.get("/non-revenue/create/")
        assert response.status_code == 200


class TestProfileRoutes:
    def test_profile_loads(self, auth_client):
        response = auth_client.get("/profile/")
        assert response.status_code == 200

    def test_change_password_form(self, auth_client):
        response = auth_client.get("/profile/change-password/")
        assert response.status_code == 200


class TestAdminRoutes:
    def test_user_management_requires_admin(self, officer_client):
        response = officer_client.get("/admin-panel/users/")
        # Should redirect or 403 for non-admin
        assert response.status_code in (302, 403)

    def test_user_management_loads_for_admin(self, auth_client):
        response = auth_client.get("/admin-panel/users/")
        assert response.status_code == 200


class TestDataRoutes:
    def test_export_page(self, auth_client):
        response = auth_client.get("/data/export/")
        assert response.status_code == 200

    def test_config_page(self, auth_client):
        response = auth_client.get("/data/admin/config/")
        assert response.status_code == 200

    def test_subdomains_api(self, auth_client):
        response = auth_client.get("/data/api/subdomains/ES/")
        assert response.status_code == 200
