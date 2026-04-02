"""
Integration tests for approval workflow routes.
"""
import pytest
from django.test import Client as TestClient
from core.models import Assignment

pytestmark = pytest.mark.django_db


class TestApprovalsPage:
    def test_approvals_requires_auth(self):
        client = TestClient()
        response = client.get("/approvals/")
        assert response.status_code == 302

    def test_approvals_loads_for_admin(self, auth_client):
        response = auth_client.get("/approvals/")
        assert response.status_code == 200

    def test_approvals_loads_for_head(self, head_client):
        response = head_client.get("/approvals/")
        assert response.status_code == 200


class TestRegistrationApproval:
    def test_approve_registration(self, auth_client, draft_assignment):
        # First submit the registration
        draft_assignment.submit_registration()
        draft_assignment.save()

        response = auth_client.post(
            f"/approvals/registration/{draft_assignment.id}/approve/",
            {"remarks": "Approved for processing"},
        )
        assert response.status_code == 302

        draft_assignment.refresh_from_db()
        assert draft_assignment.registration_status == "APPROVED"
        assert draft_assignment.workflow_stage == "TL_ASSIGNMENT"

    def test_reject_registration(self, auth_client, draft_assignment):
        draft_assignment.submit_registration()
        draft_assignment.save()

        response = auth_client.post(
            f"/approvals/registration/{draft_assignment.id}/reject/",
            {"remarks": "Incomplete information"},
        )
        assert response.status_code == 302

        draft_assignment.refresh_from_db()
        assert draft_assignment.registration_status == "REJECTED"


class TestSectionApprovals:
    def test_submit_cost_estimation(self, tl_client, sample_assignment, expenditure_heads):
        from core.models import ExpenditureItem
        sample_assignment.workflow_stage = "DETAIL_ENTRY"
        sample_assignment.cost_approval_status = "DRAFT"
        sample_assignment.save()

        # Need at least one expenditure item
        ExpenditureItem.objects.create(
            assignment=sample_assignment,
            head=expenditure_heads[0],
            estimated_amount=10.0,
        )

        response = tl_client.post(
            f"/approvals/cost/{sample_assignment.id}/submit/"
        )
        assert response.status_code == 302

        sample_assignment.refresh_from_db()
        assert sample_assignment.cost_approval_status == "SUBMITTED"

    def test_approve_cost_estimation(self, auth_client, sample_assignment):
        sample_assignment.cost_approval_status = "SUBMITTED"
        sample_assignment.save()

        response = auth_client.post(
            f"/approvals/cost/{sample_assignment.id}/approve/"
        )
        assert response.status_code == 302

        sample_assignment.refresh_from_db()
        assert sample_assignment.cost_approval_status == "APPROVED"


class TestTeamLeaderAllocation:
    def test_allocate_tl(self, auth_client, draft_assignment, team_leader_user):
        draft_assignment.submit_registration()
        draft_assignment.approve_registration()
        draft_assignment.save()

        response = auth_client.post(
            f"/approvals/allocate-tl/{draft_assignment.id}/",
            {"team_leader_id": team_leader_user.officer_id},
        )
        assert response.status_code == 302

        draft_assignment.refresh_from_db()
        assert draft_assignment.workflow_stage == "DETAIL_ENTRY"
        assert draft_assignment.team_leader == team_leader_user
