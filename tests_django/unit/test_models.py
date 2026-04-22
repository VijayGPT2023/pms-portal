"""
Unit tests for Django models — ORM, state machine, business logic.
"""
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from core.models import (
    Assignment, Client, EditRequest, ExpenditureHead, ExpenditureItem,
    InvoiceRequest, Milestone, Office, Officer, OfficerRole,
    PaymentReceipt, RevenueShare,
)
from django_fsm import TransitionNotAllowed


pytestmark = pytest.mark.django_db


# =============================================================================
# Officer (Custom User Model)
# =============================================================================

class TestOfficerModel:
    def test_create_user(self, office):
        user = Officer.objects.create_user(
            email="test@test.gov.in",
            officer_id="TEST01",
            name="Test User",
            office=office,
            password="pass123",
        )
        assert user.email == "test@test.gov.in"
        assert user.check_password("pass123")
        assert not user.is_staff
        assert not user.is_superuser

    def test_create_superuser(self):
        user = Officer.objects.create_superuser(
            email="super@test.gov.in",
            officer_id="SUPER01",
            name="Super User",
            password="pass123",
        )
        assert user.is_staff
        assert user.is_superuser
        assert user.admin_role_id == "ADMIN"

    def test_email_unique(self, office):
        Officer.objects.create_user(
            email="dup@test.gov.in", officer_id="DUP01",
            name="First", office=office, password="x",
        )
        with pytest.raises(IntegrityError):
            Officer.objects.create_user(
                email="dup@test.gov.in", officer_id="DUP02",
                name="Second", office=office, password="x",
            )

    def test_officer_id_unique(self, office):
        Officer.objects.create_user(
            email="a@test.gov.in", officer_id="UNIQ01",
            name="A", office=office, password="x",
        )
        with pytest.raises(IntegrityError):
            Officer.objects.create_user(
                email="b@test.gov.in", officer_id="UNIQ01",
                name="B", office=office, password="x",
            )

    def test_str(self, admin_user):
        assert "ADMIN" in str(admin_user)
        assert "Test Admin" in str(admin_user)

    def test_default_target(self, officer_user):
        assert officer_user.annual_target == 60.0


# =============================================================================
# Office
# =============================================================================

class TestOfficeModel:
    def test_create(self, office):
        assert office.office_id == "HQ"
        assert office.annual_target_per_officer == 60.0

    def test_office_id_unique(self, db):
        Office.objects.create(office_id="UNQ", office_name="Unique")
        with pytest.raises(IntegrityError):
            Office.objects.create(office_id="UNQ", office_name="Duplicate")


# =============================================================================
# Assignment — State Machine (django-fsm)
# =============================================================================

class TestAssignmentWorkflow:
    def test_initial_state(self, draft_assignment):
        assert draft_assignment.workflow_stage == "REGISTRATION"
        assert draft_assignment.registration_status == "DRAFT"

    def test_submit_registration(self, draft_assignment):
        draft_assignment.submit_registration()
        draft_assignment.save()
        assert draft_assignment.registration_status == "PENDING_APPROVAL"

    def test_approve_registration_moves_to_tl_assignment(self, draft_assignment):
        draft_assignment.submit_registration()
        draft_assignment.approve_registration()
        draft_assignment.save()
        assert draft_assignment.registration_status == "APPROVED"
        assert draft_assignment.workflow_stage == "TL_ASSIGNMENT"

    def test_reject_registration(self, draft_assignment):
        draft_assignment.submit_registration()
        draft_assignment.reject_registration()
        draft_assignment.save()
        assert draft_assignment.registration_status == "REJECTED"

    def test_assign_team_leader_moves_to_detail_entry(self, draft_assignment):
        draft_assignment.submit_registration()
        draft_assignment.approve_registration()
        draft_assignment.assign_team_leader()
        draft_assignment.save()
        assert draft_assignment.workflow_stage == "DETAIL_ENTRY"

    def test_cannot_skip_stages(self, draft_assignment):
        """Cannot assign TL from REGISTRATION stage."""
        from django_fsm import TransitionNotAllowed
        with pytest.raises(TransitionNotAllowed):
            draft_assignment.assign_team_leader()

    def test_all_sections_approved(self, sample_assignment):
        assert sample_assignment.all_sections_approved()

    def test_section_not_approved_blocks(self, draft_assignment):
        draft_assignment.approval_status = "APPROVED"
        draft_assignment.cost_approval_status = "APPROVED"
        draft_assignment.team_approval_status = "DRAFT"  # Not approved
        draft_assignment.milestone_approval_status = "APPROVED"
        draft_assignment.revenue_approval_status = "APPROVED"
        assert not draft_assignment.all_sections_approved()

    def test_auto_activation(self, db, office, team_leader_user):
        a = Assignment.objects.create(
            assignment_no="AUTO-ACT-001",
            title="Auto Activate Test",
            office=office,
            workflow_stage="DETAIL_ENTRY",
            registration_status="APPROVED",
            approval_status="APPROVED",
            cost_approval_status="APPROVED",
            team_approval_status="APPROVED",
            milestone_approval_status="APPROVED",
            revenue_approval_status="APPROVED",
            team_leader=team_leader_user,
        )
        a.try_auto_activate()
        a.refresh_from_db()
        assert a.workflow_stage == "ACTIVE"
        assert a.status == "Ongoing"


class TestAssignmentSectionApprovals:
    def test_submit_section(self, draft_assignment):
        draft_assignment._submit_section("cost", "TL001")
        assert draft_assignment.cost_approval_status == "SUBMITTED"
        assert draft_assignment.cost_submitted_by == "TL001"
        assert draft_assignment.cost_submitted_at is not None

    def test_approve_section(self, draft_assignment):
        draft_assignment._approve_section("team", "RDHEAD01")
        assert draft_assignment.team_approval_status == "APPROVED"
        assert draft_assignment.team_approved_by == "RDHEAD01"

    def test_reject_section(self, draft_assignment):
        draft_assignment._reject_section("milestone")
        assert draft_assignment.milestone_approval_status == "REJECTED"


# =============================================================================
# Invoice — State Machine + 80-20 Revenue
# =============================================================================

class TestInvoiceWorkflow:
    def test_approve_calculates_80_percent(self, db, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="INV-001",
            assignment=sample_assignment,
            invoice_amount=100.0,
            fy_period="2025-26",
            requested_by=officer_user,
        )
        inv.approve()
        inv.save()
        assert inv.status == "APPROVED"
        assert inv.revenue_recognized_80 == 80.0

    def test_reject_invoice(self, db, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="INV-002",
            assignment=sample_assignment,
            invoice_amount=50.0,
            fy_period="2025-26",
            requested_by=officer_user,
        )
        inv.reject()
        inv.save()
        assert inv.status == "REJECTED"

    def test_payment_auto_calculates_20_percent(self, db, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="INV-003",
            assignment=sample_assignment,
            invoice_amount=100.0,
            fy_period="2025-26",
            requested_by=officer_user,
            status="APPROVED",
        )
        pmt = PaymentReceipt(
            receipt_number="PMT-001",
            invoice_request=inv,
            amount_received=100.0,
            receipt_date="2025-12-01",
            fy_period="2025-26",
            updated_by=officer_user,
        )
        pmt.save()
        assert pmt.revenue_recognized_20 == 20.0


# =============================================================================
# Milestone
# =============================================================================

class TestMilestone:
    def test_unique_together(self, sample_assignment):
        Milestone.objects.create(
            assignment=sample_assignment, milestone_no=99, title="M99"
        )
        with pytest.raises(IntegrityError):
            Milestone.objects.create(
                assignment=sample_assignment, milestone_no=99, title="Dup"
            )

    def test_cascade_delete(self, sample_assignment, sample_milestones):
        assert Milestone.objects.filter(assignment=sample_assignment).count() == 3
        sample_assignment.delete()
        assert Milestone.objects.filter(assignment__isnull=True).count() == 0


# =============================================================================
# Revenue Share
# =============================================================================

class TestRevenueShare:
    def test_unique_per_officer_per_assignment(self, sample_assignment, officer_user):
        RevenueShare.objects.create(
            assignment=sample_assignment, officer=officer_user,
            share_percent=50, share_amount=25.0,
        )
        with pytest.raises(IntegrityError):
            RevenueShare.objects.create(
                assignment=sample_assignment, officer=officer_user,
                share_percent=30, share_amount=15.0,
            )


# =============================================================================
# Expenditure
# =============================================================================

class TestExpenditure:
    def test_head_code_unique(self, db):
        ExpenditureHead.objects.create(category="X", head_code="X1", head_name="Test")
        with pytest.raises(IntegrityError):
            ExpenditureHead.objects.create(category="X", head_code="X1", head_name="Dup")

    def test_item_unique_per_assignment_head(self, sample_assignment, expenditure_heads):
        head = expenditure_heads[0]
        ExpenditureItem.objects.create(
            assignment=sample_assignment, head=head, estimated_amount=10.0
        )
        with pytest.raises(IntegrityError):
            ExpenditureItem.objects.create(
                assignment=sample_assignment, head=head, estimated_amount=20.0
            )


# =============================================================================
# Client
# =============================================================================

class TestClient:
    def test_client_code_unique(self, db):
        Client.objects.create(client_code="UNQ", client_name="First")
        with pytest.raises(IntegrityError):
            Client.objects.create(client_code="UNQ", client_name="Second")

    def test_str(self, sample_client):
        assert "CLI001" in str(sample_client)
        assert "Test Ministry" in str(sample_client)


# =============================================================================
# OfficerRole
# =============================================================================

class TestOfficerRole:
    def test_multiple_roles(self, officer_user):
        OfficerRole.objects.create(
            officer=officer_user, role_type="TEAM_LEADER",
            scope_type="ASSIGNMENT",
        )
        OfficerRole.objects.create(
            officer=officer_user, role_type="GROUP_HEAD",
            scope_type="GROUP", scope_value="IE",
        )
        assert officer_user.roles.count() == 2


# =============================================================================
# EditRequest (SCOPE_V2 §3.5)
# =============================================================================

class TestEditRequest:
    def _make(self, assignment, officer, section=EditRequest.Section.COST, reason="bump cost"):
        return EditRequest.objects.create(
            assignment=assignment,
            section=section,
            proposed_by=officer,
            reason=reason,
        )

    def test_edit_number_auto_increments_per_section(self, sample_assignment, team_leader_user):
        e1 = self._make(sample_assignment, team_leader_user, EditRequest.Section.COST)
        e2 = self._make(sample_assignment, team_leader_user, EditRequest.Section.COST)
        e3 = self._make(sample_assignment, team_leader_user, EditRequest.Section.COST)
        assert (e1.edit_number, e2.edit_number, e3.edit_number) == (1, 2, 3)

    def test_edit_counters_are_independent_across_sections(self, sample_assignment, team_leader_user):
        cost1 = self._make(sample_assignment, team_leader_user, EditRequest.Section.COST)
        cost2 = self._make(sample_assignment, team_leader_user, EditRequest.Section.COST)
        team1 = self._make(sample_assignment, team_leader_user, EditRequest.Section.TEAM)
        assert cost1.edit_number == 1
        assert cost2.edit_number == 2
        assert team1.edit_number == 1  # independent counter

    def test_required_approver_role_gh_for_first_three(self, sample_assignment, team_leader_user):
        for expected_edit_no in (1, 2, 3):
            er = self._make(sample_assignment, team_leader_user, EditRequest.Section.TEAM)
            assert er.edit_number == expected_edit_no
            assert er.required_approver_role == "GH"

    def test_required_approver_role_ddg_from_fourth(self, sample_assignment, team_leader_user):
        for _ in range(3):
            self._make(sample_assignment, team_leader_user, EditRequest.Section.TEAM)
        fourth = self._make(sample_assignment, team_leader_user, EditRequest.Section.TEAM)
        assert fourth.edit_number == 4
        assert fourth.required_approver_role == "DDG"

    def test_approve_transition_records_reviewer(self, sample_assignment, team_leader_user, rd_head_user):
        er = self._make(sample_assignment, team_leader_user)
        er.approve(rd_head_user, notes="looks fine")
        er.save()
        er.refresh_from_db()
        assert er.status == "APPROVED"
        assert er.reviewed_by == rd_head_user
        assert er.review_notes == "looks fine"
        assert er.reviewed_at is not None

    def test_reject_requires_notes(self, sample_assignment, team_leader_user, rd_head_user):
        er = self._make(sample_assignment, team_leader_user)
        with pytest.raises(ValueError):
            er.reject(rd_head_user, notes="")

    def test_reject_transition(self, sample_assignment, team_leader_user, rd_head_user):
        er = self._make(sample_assignment, team_leader_user)
        er.reject(rd_head_user, notes="not justified")
        er.save()
        er.refresh_from_db()
        assert er.status == "REJECTED"
        assert er.review_notes == "not justified"

    def test_withdraw_transition(self, sample_assignment, team_leader_user):
        er = self._make(sample_assignment, team_leader_user)
        er.withdraw()
        er.save()
        er.refresh_from_db()
        assert er.status == "WITHDRAWN"

    def test_cannot_approve_already_approved(self, sample_assignment, team_leader_user, rd_head_user):
        er = self._make(sample_assignment, team_leader_user)
        er.approve(rd_head_user)
        er.save()
        with pytest.raises(TransitionNotAllowed):
            er.approve(rd_head_user)

    def test_next_edit_number_classmethod(self, sample_assignment, team_leader_user):
        assert EditRequest.next_edit_number(sample_assignment, EditRequest.Section.REVENUE) == 1
        self._make(sample_assignment, team_leader_user, EditRequest.Section.REVENUE)
        assert EditRequest.next_edit_number(sample_assignment, EditRequest.Section.REVENUE) == 2
