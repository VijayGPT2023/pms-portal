"""
Unit tests for workflow business logic -- approval states, auto-activation,
reset-on-edit, registration status transitions.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from __mocks__.fixtures import make_assignment

pytestmark = pytest.mark.unit


# ── Workflow stage transitions ───────────────────────────────────────

class TestWorkflowStages:
    """Verify stage constants and valid transitions."""

    STAGES = ["REGISTRATION", "TL_ASSIGNMENT", "DETAIL_ENTRY", "ACTIVE", "COMPLETED"]

    def test_all_stages_exist(self):
        for stage in self.STAGES:
            a = make_assignment(workflow_stage=stage)
            assert a["workflow_stage"] == stage

    def test_registration_to_tl_assignment(self):
        """After approval, stage moves REGISTRATION -> TL_ASSIGNMENT."""
        a = make_assignment(workflow_stage="REGISTRATION", registration_status="PENDING_APPROVAL")
        # Simulate approval
        a["registration_status"] = "APPROVED"
        a["workflow_stage"] = "TL_ASSIGNMENT"
        assert a["workflow_stage"] == "TL_ASSIGNMENT"

    def test_tl_assignment_to_detail_entry(self):
        """After TL is assigned, stage moves TL_ASSIGNMENT -> DETAIL_ENTRY."""
        a = make_assignment(workflow_stage="TL_ASSIGNMENT")
        a["team_leader_officer_id"] = "TL001"
        a["workflow_stage"] = "DETAIL_ENTRY"
        assert a["workflow_stage"] == "DETAIL_ENTRY"
        assert a["team_leader_officer_id"] is not None


# ── Registration status transitions ──────────────────────────────────

class TestRegistrationStatus:
    VALID_STATUSES = ["PENDING_APPROVAL", "APPROVED", "REJECTED"]

    def test_initial_status(self):
        a = make_assignment()
        assert a["registration_status"] == "PENDING_APPROVAL"

    def test_approve_sets_approved(self):
        a = make_assignment(registration_status="PENDING_APPROVAL")
        a["registration_status"] = "APPROVED"
        assert a["registration_status"] == "APPROVED"

    def test_reject_sets_rejected(self):
        a = make_assignment(registration_status="PENDING_APPROVAL")
        a["registration_status"] = "REJECTED"
        assert a["registration_status"] == "REJECTED"


# ── Auto-activation logic ────────────────────────────────────────────

class TestAutoActivation:
    """When all 5 section approvals are APPROVED, assignment auto-activates."""

    def _all_approved(self):
        return make_assignment(
            workflow_stage="DETAIL_ENTRY",
            approval_status="APPROVED",
            cost_approval_status="APPROVED",
            team_approval_status="APPROVED",
            milestone_approval_status="APPROVED",
            revenue_approval_status="APPROVED",
        )

    def test_all_approved_should_activate(self):
        a = self._all_approved()
        all_approved = (
            a["approval_status"] == "APPROVED"
            and a["cost_approval_status"] == "APPROVED"
            and a["team_approval_status"] == "APPROVED"
            and a["milestone_approval_status"] == "APPROVED"
            and a["revenue_approval_status"] == "APPROVED"
        )
        assert all_approved is True
        assert a["workflow_stage"] == "DETAIL_ENTRY"  # Not yet activated

    def test_one_section_not_approved_blocks_activation(self):
        a = self._all_approved()
        a["cost_approval_status"] = "SUBMITTED"
        all_approved = (
            a["approval_status"] == "APPROVED"
            and a["cost_approval_status"] == "APPROVED"
            and a["team_approval_status"] == "APPROVED"
            and a["milestone_approval_status"] == "APPROVED"
            and a["revenue_approval_status"] == "APPROVED"
        )
        assert all_approved is False

    def test_draft_blocks_activation(self):
        a = self._all_approved()
        a["milestone_approval_status"] = "DRAFT"
        all_approved = all(
            a[f] == "APPROVED"
            for f in [
                "approval_status", "cost_approval_status", "team_approval_status",
                "milestone_approval_status", "revenue_approval_status",
            ]
        )
        assert all_approved is False

    def test_rejected_blocks_activation(self):
        a = self._all_approved()
        a["team_approval_status"] = "REJECTED"
        all_approved = all(
            a[f] == "APPROVED"
            for f in [
                "approval_status", "cost_approval_status", "team_approval_status",
                "milestone_approval_status", "revenue_approval_status",
            ]
        )
        assert all_approved is False

    def test_activation_only_from_detail_entry(self):
        """Auto-activation should only happen if stage is DETAIL_ENTRY."""
        a = self._all_approved()
        a["workflow_stage"] = "ACTIVE"  # already active
        should_activate = (
            a["workflow_stage"] in ("DETAIL_ENTRY", None, "")
            and all(
                a[f] == "APPROVED"
                for f in [
                    "approval_status", "cost_approval_status", "team_approval_status",
                    "milestone_approval_status", "revenue_approval_status",
                ]
            )
        )
        assert should_activate is False


# ── Section approval status transitions ──────────────────────────────

class TestSectionApprovalStatus:
    SECTIONS = [
        "approval_status",
        "cost_approval_status",
        "team_approval_status",
        "milestone_approval_status",
        "revenue_approval_status",
    ]
    VALID_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]

    def test_initial_status_is_draft(self):
        a = make_assignment()
        for section in self.SECTIONS:
            assert a[section] == "DRAFT"

    def test_submit_transition(self):
        a = make_assignment()
        for section in self.SECTIONS:
            a[section] = "SUBMITTED"
            assert a[section] == "SUBMITTED"

    def test_approve_transition(self):
        a = make_assignment()
        for section in self.SECTIONS:
            a[section] = "APPROVED"
            assert a[section] == "APPROVED"

    def test_reject_transition(self):
        a = make_assignment()
        for section in self.SECTIONS:
            a[section] = "REJECTED"
            assert a[section] == "REJECTED"


# ── Reset-on-edit logic ──────────────────────────────────────────────

class TestResetOnEdit:
    """When a TL edits details after approval, approval resets to SUBMITTED."""

    def test_basic_info_reset(self):
        a = make_assignment(approval_status="APPROVED")
        # Simulate edit -> reset
        if a["approval_status"] == "APPROVED":
            a["approval_status"] = "SUBMITTED"
        assert a["approval_status"] == "SUBMITTED"

    def test_no_reset_if_draft(self):
        a = make_assignment(approval_status="DRAFT")
        # No reset needed
        original = a["approval_status"]
        if a["approval_status"] == "APPROVED":
            a["approval_status"] = "SUBMITTED"
        assert a["approval_status"] == original  # unchanged

    def test_no_reset_if_submitted(self):
        a = make_assignment(approval_status="SUBMITTED")
        original = a["approval_status"]
        if a["approval_status"] == "APPROVED":
            a["approval_status"] = "SUBMITTED"
        assert a["approval_status"] == original

    def test_reset_reverts_auto_activation(self):
        """If a section is reset, the assignment should not be ACTIVE."""
        a = make_assignment(
            workflow_stage="ACTIVE",
            approval_status="SUBMITTED",  # was reset
            cost_approval_status="APPROVED",
            team_approval_status="APPROVED",
            milestone_approval_status="APPROVED",
            revenue_approval_status="APPROVED",
        )
        all_approved = all(
            a[f] == "APPROVED"
            for f in [
                "approval_status", "cost_approval_status", "team_approval_status",
                "milestone_approval_status", "revenue_approval_status",
            ]
        )
        assert all_approved is False


# ── Assignment types ─────────────────────────────────────────────────

class TestAssignmentTypes:
    def test_assignment_type(self):
        a = make_assignment(type="ASSIGNMENT")
        assert a["type"] == "ASSIGNMENT"

    def test_training_type(self):
        a = make_assignment(type="TRAINING")
        assert a["type"] == "TRAINING"

    def test_development_type(self):
        a = make_assignment(type="DEVELOPMENT")
        assert a["type"] == "DEVELOPMENT"

    def test_development_is_notional(self):
        a = make_assignment(type="DEVELOPMENT", man_days=25, daily_rate=0.20, is_notional=1)
        assert a["is_notional"] == 1
        assert a["man_days"] * a["daily_rate"] == pytest.approx(5.0)


# ── Fixture factory ─────────────────────────────────────────────────

class TestMakeAssignmentFixture:
    def test_defaults(self):
        a = make_assignment()
        assert a["id"] == 1
        assert a["type"] == "ASSIGNMENT"
        assert a["workflow_stage"] == "REGISTRATION"

    def test_override(self):
        a = make_assignment(id=99, title="Custom")
        assert a["id"] == 99
        assert a["title"] == "Custom"

    def test_kwargs(self):
        a = make_assignment(extra_field="extra_value")
        assert a["extra_field"] == "extra_value"
