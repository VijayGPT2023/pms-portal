"""
Integration tests for Revenue Allocation Flags (SCOPE_V2 §3.7).

Affected officer raises a flag (reason mandatory), TL/Head addresses, flagger
withdraws. Guards: only own row, no duplicate open flag, only flagger withdraws.
"""
import pytest
from django.urls import reverse

from core.models import RevenueAllocationFlag, RevenueShare


@pytest.fixture
def shares(db, sample_assignment, team_leader_user, officer_user):
    tl_share = RevenueShare.objects.create(
        assignment=sample_assignment, officer=team_leader_user, share_percent=60.0,
    )
    off_share = RevenueShare.objects.create(
        assignment=sample_assignment, officer=officer_user, share_percent=40.0,
    )
    return {"tl": tl_share, "off": off_share}


def test_officer_can_flag_own_share(officer_client, sample_assignment, shares):
    url = reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk})
    resp = officer_client.post(url, {
        "revenue_share_id": shares["off"].pk,
        "reason": "My share should be higher given my man-days.",
    })
    assert resp.status_code == 302
    flag = RevenueAllocationFlag.objects.get(assignment=sample_assignment)
    assert flag.status == "OPEN"
    assert flag.raised_by.officer_id == "OFF001"


def test_flag_requires_reason(officer_client, sample_assignment, shares):
    url = reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk})
    resp = officer_client.post(url, {"revenue_share_id": shares["off"].pk, "reason": ""})
    assert resp.status_code == 302
    assert not RevenueAllocationFlag.objects.filter(assignment=sample_assignment).exists()


def test_officer_cannot_flag_others_share(officer_client, sample_assignment, shares):
    """OFF001 tries to flag the TL's row -> rejected."""
    url = reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk})
    resp = officer_client.post(url, {"revenue_share_id": shares["tl"].pk, "reason": "not mine"})
    assert resp.status_code == 302
    assert not RevenueAllocationFlag.objects.filter(assignment=sample_assignment).exists()


def test_no_duplicate_open_flag(officer_client, sample_assignment, shares):
    url = reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk})
    officer_client.post(url, {"revenue_share_id": shares["off"].pk, "reason": "first"})
    officer_client.post(url, {"revenue_share_id": shares["off"].pk, "reason": "second"})
    assert RevenueAllocationFlag.objects.filter(
        assignment=sample_assignment, status="OPEN").count() == 1


def test_tl_can_address_flag(tl_client, officer_client, sample_assignment, shares):
    officer_client.post(
        reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk}),
        {"revenue_share_id": shares["off"].pk, "reason": "review please"},
    )
    flag = RevenueAllocationFlag.objects.get(assignment=sample_assignment)
    resp = tl_client.post(
        reverse("core:revenue_address_flag", kwargs={"flag_id": flag.pk}),
        {"resolution_note": "Raised an EditRequest to adjust."},
    )
    assert resp.status_code == 302
    flag.refresh_from_db()
    assert flag.status == "ADDRESSED"
    assert flag.addressed_by.officer_id == "TL001"


def test_flagger_can_withdraw(officer_client, sample_assignment, shares):
    officer_client.post(
        reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk}),
        {"revenue_share_id": shares["off"].pk, "reason": "never mind soon"},
    )
    flag = RevenueAllocationFlag.objects.get(assignment=sample_assignment)
    resp = officer_client.post(reverse("core:revenue_withdraw_flag", kwargs={"flag_id": flag.pk}))
    assert resp.status_code == 302
    flag.refresh_from_db()
    assert flag.status == "WITHDRAWN"


def test_non_flagger_cannot_withdraw(tl_client, officer_client, sample_assignment, shares):
    officer_client.post(
        reverse("core:revenue_raise_flag", kwargs={"assignment_id": sample_assignment.pk}),
        {"revenue_share_id": shares["off"].pk, "reason": "mine only"},
    )
    flag = RevenueAllocationFlag.objects.get(assignment=sample_assignment)
    tl_client.post(reverse("core:revenue_withdraw_flag", kwargs={"flag_id": flag.pk}))
    flag.refresh_from_db()
    assert flag.status == "OPEN"  # TL cannot withdraw someone else's flag


def test_revenue_page_renders_with_flag_button(officer_client, sample_assignment, shares):
    resp = officer_client.get(reverse("core:revenue_share_page", kwargs={"assignment_id": sample_assignment.pk}))
    assert resp.status_code == 200
    assert b"Flag my share" in resp.content
