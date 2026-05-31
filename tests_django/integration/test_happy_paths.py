"""
Happy-path assertions for high-value POST actions.

The POST sweep (test_post_action_sweep) proves handlers don't crash. This file
goes further: it submits REALISTIC form data and asserts each action produces
the CORRECT outcome (state changes, ledger rows, auto-activation, etc.).

Focus on flows not already covered elsewhere and on the ones that had bugs:
- 5-section approve -> auto-activate (the core WO workflow)
- finance approve_invoice via the view -> 80% recognized + ledger rows
- training approval chain (programme/budget/trainer/revenue) -> status APPROVED
- training coordinator allocation
- admin assign_role / add_config_option (had redirect bugs)
- utilization tl_approve -> head_rectify -> finalize chain
"""
import pytest
from django.urls import reverse

from core.models import (
    Assignment, ConfigOption, ExpenditureHead, InvoiceRequest, Milestone,
    Officer, OfficerRevenueLedger, OfficerRole, RevenueShare, TrainerAllocation,
    TrainingProgramme, UtilizationClaim,
)

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------------
# 5-section approve -> auto-activate
# ------------------------------------------------------------------

@pytest.fixture
def detail_entry_assignment(db, office, team_leader_user):
    """Assignment in DETAIL_ENTRY with all 5 sections SUBMITTED (awaiting approval)."""
    return Assignment.objects.create(
        assignment_no="NPC/HQ/ASG/HP/0001/2025-26", type="ASSIGNMENT",
        title="Happy Path WO", office=office, status="Ongoing",
        total_value=50.0, gross_value=50.0, total_revenue=40.0,
        workflow_stage="DETAIL_ENTRY", registration_status="APPROVED",
        approval_status="APPROVED",  # page-1 already approved
        cost_approval_status="SUBMITTED", team_approval_status="SUBMITTED",
        milestone_approval_status="SUBMITTED", revenue_approval_status="SUBMITTED",
        team_leader=team_leader_user,
    )


def test_section_approvals_auto_activate(auth_client, detail_entry_assignment):
    a = detail_entry_assignment
    section_urls = [
        "core:approve_cost_estimation",
        "core:approve_team_constitution",
        "core:approve_milestone_planning",
        "core:approve_revenue_shares",
    ]
    for urlname in section_urls:
        resp = auth_client.post(reverse(urlname, kwargs={"assignment_id": a.pk}), {})
        assert resp.status_code == 302, f"{urlname} approve failed"

    a.refresh_from_db()
    assert a.cost_approval_status == "APPROVED"
    assert a.team_approval_status == "APPROVED"
    assert a.milestone_approval_status == "APPROVED"
    assert a.revenue_approval_status == "APPROVED"
    # All 5 sections approved -> auto-activated
    assert a.workflow_stage == "ACTIVE"
    assert a.status == "Ongoing"


# ------------------------------------------------------------------
# Finance approve_invoice via the view -> 80% + ledger
# ------------------------------------------------------------------

def test_approve_invoice_recognizes_80_and_writes_ledger(auth_client, office,
                                                         team_leader_user, officer_user):
    a = Assignment.objects.create(
        assignment_no="NPC/HQ/ASG/HP/INV/2025-26", type="ASSIGNMENT", title="Inv HP",
        office=office, status="Ongoing", total_value=100.0, gross_value=100.0,
        workflow_stage="ACTIVE", registration_status="APPROVED",
        approval_status="APPROVED", cost_approval_status="APPROVED",
        team_approval_status="APPROVED", milestone_approval_status="APPROVED",
        revenue_approval_status="APPROVED", team_leader=team_leader_user,
    )
    RevenueShare.objects.create(assignment=a, officer=team_leader_user,
                                share_percent=100, share_amount=100)
    inv = InvoiceRequest.objects.create(
        request_number="INV-HP-1", assignment=a, invoice_amount=100.0,
        fy_period="2025-26", requested_by=officer_user, status="PENDING",
    )
    url = reverse("core:approve_invoice", kwargs={"request_id": inv.pk})
    resp = auth_client.post(url, {})
    assert resp.status_code == 302
    inv.refresh_from_db()
    assert inv.status == "APPROVED"
    assert inv.revenue_recognized_80 == pytest.approx(80.0)  # 80% of 100
    # Ledger row created for the team officer
    led = OfficerRevenueLedger.objects.filter(invoice_request=inv, revenue_type="INVOICE_80")
    assert led.count() == 1
    assert led.first().amount == pytest.approx(80.0)  # 100% share of 80


# ------------------------------------------------------------------
# Training approval chain (these had the approvals_list redirect bug)
# ------------------------------------------------------------------

@pytest.fixture
def programme(db, office, team_leader_user):
    return TrainingProgramme.objects.create(
        programme_number="TRN-HP-1", title="HP Training", office=office,
        coordinator=team_leader_user, created_by=team_leader_user, stage="ANNOUNCED",
    )


def test_training_approval_chain(auth_client, programme):
    steps = [
        ("core:approve_training", "approval_status"),
        ("core:approve_training_budget", "budget_approval_status"),
        ("core:approve_trainer_allocation", "trainer_approval_status"),
        ("core:approve_training_revenue", "revenue_approval_status"),
    ]
    for urlname, field in steps:
        resp = auth_client.post(reverse(urlname, kwargs={"programme_id": programme.pk}), {})
        assert resp.status_code == 302, f"{urlname} did not redirect (was the redirect-bug)"
        programme.refresh_from_db()
        assert getattr(programme, field) == "APPROVED", f"{field} not set"


def test_training_allocate_coordinator(auth_client, programme, officer_user):
    url = reverse("core:allocate_coordinator", kwargs={"programme_id": programme.pk})
    resp = auth_client.post(url, {"coordinator_id": officer_user.officer_id})
    assert resp.status_code == 302
    programme.refresh_from_db()
    assert programme.coordinator_id == officer_user.officer_id
    # coordinator auto-added as a trainer
    assert TrainerAllocation.objects.filter(programme=programme, officer=officer_user).exists()


# ------------------------------------------------------------------
# Admin actions (had admin_users / admin_config redirect bugs)
# ------------------------------------------------------------------

def test_assign_role(auth_client, officer_user):
    url = reverse("core:assign_role")
    resp = auth_client.post(url, {
        "officer_id": officer_user.officer_id, "role_type": "TEAM_LEADER",
        "scope_type": "GLOBAL", "is_primary": "1",
    })
    assert resp.status_code == 302  # redirect (was NoReverseMatch 500)
    assert OfficerRole.objects.filter(
        officer=officer_user, role_type="TEAM_LEADER", effective_to__isnull=True
    ).exists()


def test_add_config_option(auth_client):
    url = reverse("core:add_config_option")
    resp = auth_client.post(url, {
        "category": "test_cat", "option_value": "TST", "option_label": "Test",
        "sort_order": "1",
    })
    assert resp.status_code == 302  # redirect (was NoReverseMatch 500)
    assert ConfigOption.objects.filter(category="test_cat", option_value="TST").exists()


# ------------------------------------------------------------------
# Utilization chain: submit -> tl_approve -> head_rectify -> finalize
# ------------------------------------------------------------------

def test_utilization_approval_chain(auth_client, office, team_leader_user):
    from datetime import date
    claim = UtilizationClaim.objects.create(
        claim_number="UC-HP-1", officer=team_leader_user, claim_month="2026-05",
        activity_date=date(2026, 5, 1), man_days_claimed=5, status="SUBMITTED",
    )
    # TL approves
    r1 = auth_client.post(reverse("core:tl_approve", kwargs={"claim_id": claim.pk}), {"remarks": "ok"})
    assert r1.status_code == 302
    claim.refresh_from_db(); assert claim.status == "TL_APPROVED"
    # Head rectifies down to 4 days
    r2 = auth_client.post(reverse("core:head_rectify", kwargs={"claim_id": claim.pk}),
                          {"rectified_days": "4", "remarks": "adjusted"})
    assert r2.status_code == 302
    claim.refresh_from_db()
    assert claim.status == "HEAD_RECTIFIED"
    assert claim.rectified_days == 4
    # Finalize
    r3 = auth_client.post(reverse("core:finalize_claim", kwargs={"claim_id": claim.pk}), {})
    assert r3.status_code == 302
    claim.refresh_from_db(); assert claim.status == "FINAL"
