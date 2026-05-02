"""
Integration tests for EditRequest workflow (SCOPE_V2 §3.5).

Covers: propose form (GET/POST), inbox, detail, approve+apply, reject, withdraw,
guard against duplicate pending, edit-number escalation (GH for 1-3, DDG for 4+).
"""
import json

import pytest
from django.test import Client as TestClient
from django.urls import reverse

from core.models import (
    AssignmentTeam,
    EditRequest,
    ExpenditureItem,
    Officer,
    OfficerRole,
    RevenueShare,
)


# ------------------------------------------------------------------
# Fixtures specific to EditRequest tests
# ------------------------------------------------------------------

@pytest.fixture
def cost_lines(db, sample_assignment, expenditure_heads):
    """Seed an approved-section assignment with two cost lines."""
    items = []
    for h, amt in [(expenditure_heads[0], 1000.0), (expenditure_heads[1], 2000.0)]:
        items.append(ExpenditureItem.objects.create(
            assignment=sample_assignment, head=h,
            estimated_amount=amt, remarks="initial",
        ))
    return items


@pytest.fixture
def team_lines(db, sample_assignment, team_leader_user, officer_user):
    AssignmentTeam.objects.create(
        assignment=sample_assignment, officer=team_leader_user,
        role="TEAM_LEADER", is_active=True,
    )
    AssignmentTeam.objects.create(
        assignment=sample_assignment, officer=officer_user,
        role="MEMBER", is_active=True,
    )
    return list(AssignmentTeam.objects.filter(assignment=sample_assignment))


@pytest.fixture
def revenue_lines(db, sample_assignment, team_leader_user, officer_user):
    RevenueShare.objects.create(
        assignment=sample_assignment, officer=team_leader_user, share_percent=60.0,
    )
    RevenueShare.objects.create(
        assignment=sample_assignment, officer=officer_user, share_percent=40.0,
    )
    return list(RevenueShare.objects.filter(assignment=sample_assignment))


@pytest.fixture
def ddg_user(db, office):
    user = Officer.objects.create_user(
        email="ddg@test.gov.in", officer_id="DDG01", name="DDG Test",
        office=office, password="testpass123", admin_role_id="DDG-I",
    )
    return user


@pytest.fixture
def ddg_client(ddg_user):
    c = TestClient()
    c.login(email="ddg@test.gov.in", password="testpass123")
    return c


# ------------------------------------------------------------------
# Cost section flow
# ------------------------------------------------------------------

def test_propose_form_get_renders(tl_client, sample_assignment, cost_lines, expenditure_heads):
    url = reverse("core:edit_request_propose",
                  kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    resp = tl_client.get(url)
    assert resp.status_code == 200
    assert b"Propose Cost Edit" in resp.content


def test_propose_blocks_non_tl(officer_client, sample_assignment, cost_lines):
    url = reverse("core:edit_request_propose",
                  kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    resp = officer_client.get(url)
    assert resp.status_code == 302  # redirected with error


def test_propose_blocks_when_section_not_approved(tl_client, draft_assignment):
    url = reverse("core:edit_request_propose",
                  kwargs={"assignment_id": draft_assignment.pk, "section": "COST"})
    resp = tl_client.get(url)
    assert resp.status_code == 302


def test_propose_cost_creates_edit_request(tl_client, sample_assignment, cost_lines, expenditure_heads):
    url = reverse("core:edit_request_propose",
                  kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    resp = tl_client.post(url, {
        "head_code": [cost_lines[0].head.head_code, cost_lines[1].head.head_code],
        "estimated_amount": ["1500.00", "2000.00"],
        "remarks": ["bumped", "initial"],
        "reason": "Cost overrun on consultant fee.",
    })
    assert resp.status_code == 302
    er = EditRequest.objects.get(assignment=sample_assignment, section="COST")
    assert er.status == "PENDING"
    assert er.edit_number == 1
    assert er.required_approver_role == "GH"
    change = json.loads(er.change_data)
    assert change["section"] == "COST"
    assert any(r["estimated_amount"] == 1500.0 for r in change["new"])


def test_propose_requires_reason(tl_client, sample_assignment, cost_lines, expenditure_heads):
    url = reverse("core:edit_request_propose",
                  kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    resp = tl_client.post(url, {
        "head_code": [cost_lines[0].head.head_code],
        "estimated_amount": ["999"],
        "remarks": [""],
        "reason": "",
    })
    assert resp.status_code == 200  # re-render
    assert not EditRequest.objects.filter(assignment=sample_assignment).exists()


def test_only_one_pending_per_section(tl_client, sample_assignment, cost_lines, expenditure_heads):
    EditRequest.objects.create(
        assignment=sample_assignment, section="COST",
        proposed_by=sample_assignment.team_leader,
        reason="prior", change_data="{}",
    )
    url = reverse("core:edit_request_propose",
                  kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    resp = tl_client.get(url)
    assert resp.status_code == 302  # redirected to existing request
    assert EditRequest.objects.filter(assignment=sample_assignment, section="COST").count() == 1


def test_approve_applies_change_data(head_client, tl_client, sample_assignment, cost_lines, expenditure_heads, rd_head_user):
    # TL proposes
    propose_url = reverse("core:edit_request_propose",
                          kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    tl_client.post(propose_url, {
        "head_code": [cost_lines[0].head.head_code, cost_lines[1].head.head_code],
        "estimated_amount": ["1500.00", "2500.00"],
        "remarks": ["bumped", "bumped"],
        "reason": "Both heads need raise.",
    })
    er = EditRequest.objects.get(assignment=sample_assignment, section="COST")

    # GH approves
    approve_url = reverse("core:edit_request_approve", kwargs={"request_id": er.pk})
    resp = head_client.post(approve_url, {"review_notes": "ok"})
    assert resp.status_code == 302
    er.refresh_from_db()
    assert er.status == "APPROVED"
    assert er.reviewed_by_id == rd_head_user.officer_id

    # Verify the cost lines were updated
    items = {ei.head.head_code: ei.estimated_amount
             for ei in ExpenditureItem.objects.filter(assignment=sample_assignment).select_related("head")}
    assert items[cost_lines[0].head.head_code] == 1500.0
    assert items[cost_lines[1].head.head_code] == 2500.0


def test_reject_requires_notes(head_client, tl_client, sample_assignment, cost_lines, expenditure_heads):
    propose_url = reverse("core:edit_request_propose",
                          kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    tl_client.post(propose_url, {
        "head_code": [cost_lines[0].head.head_code],
        "estimated_amount": ["1500"],
        "remarks": [""],
        "reason": "test",
    })
    er = EditRequest.objects.get(assignment=sample_assignment, section="COST")

    reject_url = reverse("core:edit_request_reject", kwargs={"request_id": er.pk})
    # No notes -> still PENDING
    head_client.post(reject_url, {"review_notes": ""})
    er.refresh_from_db()
    assert er.status == "PENDING"

    # With notes -> REJECTED
    head_client.post(reject_url, {"review_notes": "needs more justification"})
    er.refresh_from_db()
    assert er.status == "REJECTED"


def test_withdraw_only_by_proposer(tl_client, head_client, sample_assignment, cost_lines, expenditure_heads):
    propose_url = reverse("core:edit_request_propose",
                          kwargs={"assignment_id": sample_assignment.pk, "section": "COST"})
    tl_client.post(propose_url, {
        "head_code": [cost_lines[0].head.head_code],
        "estimated_amount": ["999"],
        "remarks": [""],
        "reason": "test",
    })
    er = EditRequest.objects.get(assignment=sample_assignment, section="COST")

    withdraw_url = reverse("core:edit_request_withdraw", kwargs={"request_id": er.pk})
    # Head cannot withdraw
    head_client.post(withdraw_url)
    er.refresh_from_db()
    assert er.status == "PENDING"

    # TL can withdraw
    tl_client.post(withdraw_url)
    er.refresh_from_db()
    assert er.status == "WITHDRAWN"


# ------------------------------------------------------------------
# Edit-number escalation: edits 1-3 → GH, edits 4+ → DDG
# ------------------------------------------------------------------

def test_edit_4_routes_to_ddg(tl_client, sample_assignment, cost_lines):
    proposer = sample_assignment.team_leader
    for n in range(1, 4):
        EditRequest.objects.create(
            assignment=sample_assignment, section="COST",
            proposed_by=proposer, reason=f"edit {n}",
            change_data="{}", status="APPROVED", edit_number=n,
        )
    er4 = EditRequest.objects.create(
        assignment=sample_assignment, section="COST",
        proposed_by=proposer, reason="edit 4", change_data="{}",
    )
    assert er4.edit_number == 4
    assert er4.required_approver_role == "DDG"


def test_gh_cannot_approve_ddg_edit(head_client, sample_assignment, cost_lines):
    proposer = sample_assignment.team_leader
    for n in range(1, 4):
        EditRequest.objects.create(
            assignment=sample_assignment, section="COST",
            proposed_by=proposer, reason=f"e{n}", change_data="{}",
            status="APPROVED", edit_number=n,
        )
    er4 = EditRequest.objects.create(
        assignment=sample_assignment, section="COST",
        proposed_by=proposer, reason="e4",
        change_data=json.dumps({"section": "COST", "old": [], "new": []}),
    )
    approve_url = reverse("core:edit_request_approve", kwargs={"request_id": er4.pk})
    head_client.post(approve_url, {"review_notes": "ok"})
    er4.refresh_from_db()
    assert er4.status == "PENDING"  # GH not authorized for DDG-tier edit


def test_ddg_can_approve_ddg_edit(ddg_client, sample_assignment, cost_lines):
    proposer = sample_assignment.team_leader
    for n in range(1, 4):
        EditRequest.objects.create(
            assignment=sample_assignment, section="COST",
            proposed_by=proposer, reason=f"e{n}", change_data="{}",
            status="APPROVED", edit_number=n,
        )
    er4 = EditRequest.objects.create(
        assignment=sample_assignment, section="COST",
        proposed_by=proposer, reason="e4",
        change_data=json.dumps({"section": "COST", "old": [], "new": []}),
    )
    approve_url = reverse("core:edit_request_approve", kwargs={"request_id": er4.pk})
    resp = ddg_client.post(approve_url, {"review_notes": "ok"})
    assert resp.status_code == 302
    er4.refresh_from_db()
    assert er4.status == "APPROVED"


# ------------------------------------------------------------------
# Inbox visibility
# ------------------------------------------------------------------

def test_inbox_shows_actionable_for_head(head_client, sample_assignment, cost_lines):
    EditRequest.objects.create(
        assignment=sample_assignment, section="COST",
        proposed_by=sample_assignment.team_leader,
        reason="x", change_data="{}",
    )
    resp = head_client.get(reverse("core:edit_request_inbox"))
    assert resp.status_code == 200
    assert b"Pending Your Review" in resp.content


def test_inbox_shows_my_requests(tl_client, sample_assignment, cost_lines):
    EditRequest.objects.create(
        assignment=sample_assignment, section="COST",
        proposed_by=sample_assignment.team_leader,
        reason="x", change_data="{}",
    )
    resp = tl_client.get(reverse("core:edit_request_inbox"))
    assert resp.status_code == 200
    assert b"My Recent Requests" in resp.content


# ------------------------------------------------------------------
# Revenue: 100% sum invariant
# ------------------------------------------------------------------

def test_revenue_apply_rejects_non_100_sum(head_client, tl_client, sample_assignment, revenue_lines, team_leader_user, officer_user):
    propose_url = reverse("core:edit_request_propose",
                          kwargs={"assignment_id": sample_assignment.pk, "section": "REVENUE"})
    tl_client.post(propose_url, {
        "officer_id": [team_leader_user.officer_id, officer_user.officer_id],
        "share_percent": ["70", "20"],  # sums to 90, not 100
        "reason": "Reallocate.",
    })
    er = EditRequest.objects.get(assignment=sample_assignment, section="REVENUE")

    approve_url = reverse("core:edit_request_approve", kwargs={"request_id": er.pk})
    head_client.post(approve_url, {"review_notes": "ok"})
    er.refresh_from_db()
    assert er.status == "PENDING"  # apply failed, transition reverted


def test_revenue_apply_with_100_sum(head_client, tl_client, sample_assignment, revenue_lines, team_leader_user, officer_user):
    propose_url = reverse("core:edit_request_propose",
                          kwargs={"assignment_id": sample_assignment.pk, "section": "REVENUE"})
    tl_client.post(propose_url, {
        "officer_id": [team_leader_user.officer_id, officer_user.officer_id],
        "share_percent": ["55", "45"],
        "reason": "Reallocate.",
    })
    er = EditRequest.objects.get(assignment=sample_assignment, section="REVENUE")

    approve_url = reverse("core:edit_request_approve", kwargs={"request_id": er.pk})
    head_client.post(approve_url, {"review_notes": "ok"})
    er.refresh_from_db()
    assert er.status == "APPROVED"
    shares = {rs.officer_id: rs.share_percent
              for rs in RevenueShare.objects.filter(assignment=sample_assignment)}
    assert shares[team_leader_user.officer_id] == 55.0
    assert shares[officer_user.officer_id] == 45.0
