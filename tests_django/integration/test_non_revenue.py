"""
Integration tests for Non-Revenue / Development Work (SCOPE_V2 §3.4).

Covers: create with man-days, GH approve allocates + moves to IN_PROGRESS,
progress update bumps man-days, complete, and the URL-name redirects resolve
(regression guard for the prior core:non_revenue_view name mismatch).
"""
import pytest
from django.urls import reverse

from core.models import NonRevenueSuggestion


@pytest.fixture
def task(db, office, officer_user):
    return NonRevenueSuggestion.objects.create(
        suggestion_number="NR-HQ-202605-001",
        title="Internal process documentation",
        activity_type="DOCUMENTATION",
        office=office,
        man_days=3.0,
        status="PENDING_APPROVAL",
        approval_status="PENDING",
        created_by=officer_user,
    )


def test_create_captures_man_days(officer_client, office):
    resp = officer_client.post(reverse("core:non_revenue_create"), {
        "office_id": office.office_id,
        "title": "R&D scan",
        "activity_type": "RESEARCH",
        "man_days": "5.5",
    })
    assert resp.status_code == 302
    s = NonRevenueSuggestion.objects.get(title="R&D scan")
    assert s.man_days == 5.5
    assert s.approval_status == "PENDING"


def test_list_renders(officer_client, task):
    resp = officer_client.get(reverse("core:non_revenue_list"))
    assert resp.status_code == 200
    assert b"Development Work" in resp.content
    assert b"NR-HQ-202605-001" in resp.content


def test_view_renders_and_redirect_name_resolves(officer_client, task):
    """Regression: view previously redirected to a non-existent URL name."""
    resp = officer_client.get(reverse("core:non_revenue_view", kwargs={"suggestion_id": task.pk}))
    assert resp.status_code == 200
    assert b"Man-days booked" in resp.content


def test_head_approve_allocates_and_progresses(auth_client, task, officer_user):
    url = reverse("core:non_revenue_approve", kwargs={"suggestion_id": task.pk})
    resp = auth_client.post(url, {"officer_id": officer_user.officer_id})
    assert resp.status_code == 302  # redirect resolves (name exists)
    task.refresh_from_db()
    assert task.approval_status == "APPROVED"
    assert task.status == "IN_PROGRESS"
    assert task.officer_id == officer_user.officer_id


def test_progress_update_bumps_man_days(auth_client, task):
    task.approval_status = "APPROVED"
    task.status = "IN_PROGRESS"
    task.save(update_fields=["approval_status", "status"])
    url = reverse("core:non_revenue_update", kwargs={"suggestion_id": task.pk})
    resp = auth_client.post(url, {"man_days": "8", "current_update": "halfway"})
    assert resp.status_code == 302
    task.refresh_from_db()
    assert task.man_days == 8.0
    assert task.current_update == "halfway"


def test_complete(auth_client, task):
    task.approval_status = "APPROVED"
    task.status = "IN_PROGRESS"
    task.save(update_fields=["approval_status", "status"])
    url = reverse("core:non_revenue_complete", kwargs={"suggestion_id": task.pk})
    resp = auth_client.post(url)
    assert resp.status_code == 302
    task.refresh_from_db()
    assert task.status == "COMPLETED"
