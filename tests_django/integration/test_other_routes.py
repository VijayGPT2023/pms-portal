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
        assert b"Client Database" in response.content
        assert b"coming soon" not in response.content

    def test_new_client_form(self, auth_client):
        response = auth_client.get("/clients/new/")
        assert response.status_code == 200
        assert b"New Client" in response.content
        assert b"coming soon" not in response.content

    def test_client_view(self, auth_client, sample_client):
        response = auth_client.get(f"/clients/{sample_client.id}/view/")
        assert response.status_code == 200
        assert b"Linked Assignments" in response.content
        assert b"coming soon" not in response.content

    def test_client_mis(self, auth_client):
        response = auth_client.get("/clients/mis/")
        assert response.status_code == 200
        assert b"Client Analytics" in response.content
        assert b"coming soon" not in response.content

    def test_create_client_roundtrip(self, auth_client):
        resp = auth_client.post("/clients/new/submit/", {
            "client_name": "UAT Test Ministry",
            "client_type": "Central Government",
            "city": "New Delhi",
        })
        assert resp.status_code == 302
        from core.models import Client
        assert Client.objects.filter(client_name="UAT Test Ministry").exists()


class TestTrainingRoutes:
    def test_training_list_loads(self, auth_client):
        response = auth_client.get("/training/")
        assert response.status_code == 200
        assert b"Training Programmes" in response.content
        assert b"coming soon" not in response.content  # real template, not stub

    def test_training_create_form(self, auth_client):
        response = auth_client.get("/training/create/")
        assert response.status_code == 200
        assert b"New Training Programme" in response.content
        assert b"coming soon" not in response.content

    def test_training_create_and_view(self, auth_client, office):
        resp = auth_client.post("/training/create/submit/", {
            "title": "UAT Lean Workshop",
            "office_id": office.office_id,
            "budgeted_participants": "20",
            "fee_per_participant": "1500",
        })
        assert resp.status_code == 302
        from core.models import TrainingProgramme
        p = TrainingProgramme.objects.get(title="UAT Lean Workshop")
        assert p.budgeted_revenue == 30000

    def test_trainer_allocation_form(self, auth_client, office):
        from core.models import TrainingProgramme
        p = TrainingProgramme.objects.create(
            programme_number="TRN-HQ-T-001", title="T", office=office, stage="ANNOUNCED",
        )
        resp = auth_client.get(f"/training/trainers/{p.pk}/")
        assert resp.status_code == 200
        assert b"Faculty Allocation" in resp.content
        assert b"coming soon" not in resp.content


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

    def test_physical_progress_tab(self, auth_client):
        # Standalone report retired (SCOPE_V2 §3.8) — now a dashboard tab.
        response = auth_client.get("/dashboard/?active_tab=physical_progress")
        assert response.status_code == 200

    def test_financial_progress_tab(self, auth_client):
        response = auth_client.get("/dashboard/?active_tab=financial_progress")
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
    # Legacy 6-tab MIS retired (SCOPE_V2 §3.8). MIS V2 dashboards covered
    # by test_mis_v2.py.
    def test_mis_pre_wo(self, auth_client):
        response = auth_client.get("/mis/pre-wo/")
        assert response.status_code == 200

    def test_mis_revenue(self, auth_client):
        response = auth_client.get("/mis/revenue/")
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
        assert b"User Management" in response.content
        assert b"coming soon" not in response.content

    def test_roles_management_loads_for_admin(self, auth_client):
        response = auth_client.get("/admin-panel/roles/")
        assert response.status_code == 200
        assert b"Assign Role" in response.content
        assert b"coming soon" not in response.content


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
