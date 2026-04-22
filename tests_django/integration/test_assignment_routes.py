"""
Integration tests for assignment routes.
"""
import pytest
from django.test import Client as TestClient
from core.models import Assignment, Milestone

pytestmark = pytest.mark.django_db


class TestAssignmentPages:
    def test_register_activity_requires_auth(self):
        client = TestClient()
        response = client.get("/assignment/register/")
        assert response.status_code == 302

    def test_register_activity_loads(self, auth_client):
        response = auth_client.get("/assignment/register/")
        assert response.status_code == 200

    def test_workorders_list_loads(self, auth_client):
        response = auth_client.get("/assignment/workorders/")
        assert response.status_code == 200

    def test_select_activity_type_loads(self, auth_client):
        response = auth_client.get("/assignment/select-activity-type/")
        assert response.status_code == 200

    def test_view_assignment(self, auth_client, sample_assignment):
        response = auth_client.get(f"/assignment/view/{sample_assignment.id}/")
        assert response.status_code == 200

    def test_view_nonexistent_assignment_404(self, auth_client):
        response = auth_client.get("/assignment/view/99999/")
        assert response.status_code == 404

    def test_assignments_list_loads(self, auth_client):
        response = auth_client.get("/mis/assignments/")
        assert response.status_code == 200


class TestAssignmentRegistration:
    def test_register_creates_draft(self, auth_client, office):
        response = auth_client.post("/assignment/register/", {
            "title": "New Study",
            "office_id": "HQ",
        })
        assert response.status_code == 302
        a = Assignment.objects.filter(title="New Study").first()
        assert a is not None
        # View auto-submits registration, so status is PENDING_APPROVAL
        assert a.registration_status in ("DRAFT", "PENDING_APPROVAL")
        assert a.workflow_stage == "REGISTRATION"


class TestMilestones:
    def test_milestones_page_loads(self, auth_client, sample_assignment):
        response = auth_client.get(f"/assignment/milestones/{sample_assignment.id}/")
        assert response.status_code == 200

    def test_add_milestone(self, auth_client, sample_assignment):
        response = auth_client.post(f"/assignment/milestones/{sample_assignment.id}/", {
            "milestone_count": "1",
            "title_1": "First Milestone",
            "target_date_1": "2026-06-30",
            "invoice_percent_1": "100",
        })
        assert response.status_code == 302


class TestExpenditure:
    def test_expenditure_page_loads(self, auth_client, sample_assignment):
        response = auth_client.get(f"/assignment/expenditure/{sample_assignment.id}/")
        assert response.status_code == 200


class TestRetrospectiveFill:
    """SCOPE_V2 §3.6 — retrospective data entry for bulk-onboarded assignments."""

    def test_requires_auth(self, sample_assignment):
        client = TestClient()
        response = client.get(f"/assignment/retrospective-fill/{sample_assignment.id}/")
        assert response.status_code == 302  # login redirect

    def test_redirects_when_not_bulk_onboarded(self, auth_client, sample_assignment):
        assert sample_assignment.is_bulk_onboarded is False
        response = auth_client.get(f"/assignment/retrospective-fill/{sample_assignment.id}/")
        assert response.status_code == 302

    def test_loads_for_bulk_onboarded(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.get(f"/assignment/retrospective-fill/{sample_assignment.id}/")
        assert response.status_code == 200
        assert b"Retrospective Data Entry" in response.content

    def test_post_saves_as_of_date_and_physical_percent(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"as_of_date": "2026-03-31", "physical_progress_percent": "65.5"},
        )
        assert response.status_code == 302
        sample_assignment.refresh_from_db()
        assert str(sample_assignment.bulk_onboarding_as_of_date) == "2026-03-31"
        assert sample_assignment.physical_progress_percent == 65.5

    def test_post_rejects_out_of_range_percent(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"physical_progress_percent": "150"},
        )
        assert response.status_code == 302
        sample_assignment.refresh_from_db()
        assert sample_assignment.physical_progress_percent == 0  # unchanged
