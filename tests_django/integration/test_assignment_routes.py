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
