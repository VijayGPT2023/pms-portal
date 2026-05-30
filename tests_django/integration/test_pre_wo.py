"""
Integration tests for the Pre-WO pipeline (SCOPE_V2 §3.1).

Covers: create by any officer, list + funnel, GH approve/reject, close outcomes,
record-number generation, and office scoping.
"""
import pytest
from django.urls import reverse

from core.models import PreWORecord


@pytest.fixture
def enquiry(db, regional_office, rd_head_user):
    """A PENDING enquiry in the RD office (so rd_head_user is in-scope)."""
    return PreWORecord.objects.create(
        record_number="ENQ-RDDEL-202605-001",
        stage="ENQUIRY",
        title="Productivity study enquiry",
        client="State PWD",
        office=regional_office,
        owner=rd_head_user,
        created_by=rd_head_user,
    )


# ------------------------------------------------------------------
# Create (any officer)
# ------------------------------------------------------------------

def test_officer_can_create_record(officer_client, office):
    url = reverse("core:pre_wo_create")
    resp = officer_client.post(url, {
        "office_id": office.office_id,
        "stage": "ENQUIRY",
        "title": "New enquiry from a PSU",
        "client": "BHEL",
        "expected_value": "500000",
    })
    assert resp.status_code == 302
    rec = PreWORecord.objects.get(title="New enquiry from a PSU")
    assert rec.approval_status == "PENDING"
    assert rec.outcome == "OPEN"
    assert rec.owner.officer_id == "OFF001"
    assert rec.record_number.startswith("ENQ-HQ-")


def test_record_number_prefix_per_stage(officer_client, office):
    url = reverse("core:pre_wo_create")
    officer_client.post(url, {"office_id": office.office_id, "stage": "PROPOSAL", "title": "Proposal X"})
    rec = PreWORecord.objects.get(title="Proposal X")
    assert rec.record_number.startswith("PRP-HQ-")


def test_list_renders_with_funnel(officer_client, office):
    PreWORecord.objects.create(record_number="ENQ-HQ-1", stage="ENQUIRY", title="A", office=office)
    PreWORecord.objects.create(record_number="PRP-HQ-1", stage="PROPOSAL", title="B", office=office)
    resp = officer_client.get(reverse("core:pre_wo_list"))
    assert resp.status_code == 200
    assert b"Pre-WO Pipeline" in resp.content


# ------------------------------------------------------------------
# Approval (GH/RD only)
# ------------------------------------------------------------------

def test_head_can_approve(head_client, enquiry):
    url = reverse("core:pre_wo_approve", kwargs={"record_id": enquiry.pk})
    resp = head_client.post(url)
    assert resp.status_code == 302
    enquiry.refresh_from_db()
    assert enquiry.approval_status == "APPROVED"
    assert enquiry.approved_by.officer_id == "RDHEAD01"


def test_officer_cannot_approve(officer_client, enquiry):
    url = reverse("core:pre_wo_approve", kwargs={"record_id": enquiry.pk})
    officer_client.post(url)
    enquiry.refresh_from_db()
    assert enquiry.approval_status == "PENDING"


def test_reject_requires_reason(head_client, enquiry):
    url = reverse("core:pre_wo_reject", kwargs={"record_id": enquiry.pk})
    # No reason -> stays pending
    head_client.post(url, {"rejection_reason": ""})
    enquiry.refresh_from_db()
    assert enquiry.approval_status == "PENDING"
    # With reason -> rejected
    head_client.post(url, {"rejection_reason": "Out of scope"})
    enquiry.refresh_from_db()
    assert enquiry.approval_status == "REJECTED"
    assert enquiry.rejection_reason == "Out of scope"


# ------------------------------------------------------------------
# Close outcomes
# ------------------------------------------------------------------

def test_close_requires_approval_first(head_client, enquiry):
    """A PENDING record cannot be closed."""
    url = reverse("core:pre_wo_close", kwargs={"record_id": enquiry.pk})
    head_client.post(url, {"outcome": "DROPPED"})
    enquiry.refresh_from_db()
    assert enquiry.outcome == "OPEN"


def test_close_dropped(head_client, enquiry):
    enquiry.approval_status = "APPROVED"
    enquiry.save(update_fields=["approval_status"])
    url = reverse("core:pre_wo_close", kwargs={"record_id": enquiry.pk})
    head_client.post(url, {"outcome": "DROPPED", "outcome_reason": "Client lost interest"})
    enquiry.refresh_from_db()
    assert enquiry.outcome == "DROPPED"
    assert enquiry.outcome_reason == "Client lost interest"


def test_close_converted_links_assignment(head_client, enquiry, sample_assignment):
    enquiry.approval_status = "APPROVED"
    enquiry.save(update_fields=["approval_status"])
    url = reverse("core:pre_wo_close", kwargs={"record_id": enquiry.pk})
    head_client.post(url, {"outcome": "CONVERTED_TO_WO", "assignment_id": sample_assignment.pk})
    enquiry.refresh_from_db()
    assert enquiry.outcome == "CONVERTED_TO_WO"
    assert enquiry.converted_assignment_id == sample_assignment.pk


# ------------------------------------------------------------------
# Office scoping
# ------------------------------------------------------------------

def test_officer_sees_only_own_office(officer_client, office, regional_office):
    # HQ record (officer's office) + RD record (other office)
    PreWORecord.objects.create(record_number="ENQ-HQ-9", stage="ENQUIRY", title="HQ one", office=office)
    PreWORecord.objects.create(record_number="ENQ-RDDEL-9", stage="ENQUIRY", title="RD one", office=regional_office)
    resp = officer_client.get(reverse("core:pre_wo_list"))
    assert b"HQ one" in resp.content
    assert b"RD one" not in resp.content


def test_admin_sees_all_offices(auth_client, office, regional_office):
    PreWORecord.objects.create(record_number="ENQ-HQ-8", stage="ENQUIRY", title="HQ rec", office=office)
    PreWORecord.objects.create(record_number="ENQ-RDDEL-8", stage="ENQUIRY", title="RD rec", office=regional_office)
    resp = auth_client.get(reverse("core:pre_wo_list"))
    assert b"HQ rec" in resp.content
    assert b"RD rec" in resp.content
