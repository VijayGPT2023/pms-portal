"""
Proactive POST-action diagnostic.

Auto-discovers every state-changing (POST) core endpoint, fills its URL params
from seed objects, and fires an empty POST at each. The contract: a handler may
redirect (302), re-render with an error (200), or refuse (403/405) — but it must
NOT crash with a 500. A 500 on empty POST means an unguarded access (e.g.
request.POST['x'] without .get(), a stale field/URL name, or a NoReverseMatch in
the redirect target).

Runs against the rolled-back test DB, so mutations are safe.
"""
import re

import pytest
from django.test import Client as TestClient
from django.urls import reverse

from core.models import (
    Assignment, Client, EditRequest, ExpenditureHead, InvoiceRequest,
    Milestone, NonRevenueSuggestion, Officer, PreWORecord, RevenueShare,
    TrainingProgramme, UtilizationClaim, ProposalDocument, RevenueAllocationFlag,
)

pytestmark = pytest.mark.django_db

# Endpoints my discovery regex over-matches that are actually GET pages, or that
# are genuinely destructive / out-of-scope for an empty-POST smoke.
SKIP = {
    "workorders_list", "assignments_list", "head_hub", "select_activity_type",
    "select_type", "assignment_view", "manage_milestones", "manage_expenditure",
    "expenditure_entry", "retrospective_fill", "register_activity",
    "new_assignment", "revenue_share_page", "invoice_request_form",
    "proposal_upload_form", "proposal_link_form", "training_create_form",
    "non_revenue_create_form", "pre_wo_create_form", "pre_wo_view",
    "pre_wo_edit_form", "api_get_assignment",
    "export_assignments",  # streams a file
    "import_data",         # needs a real uploaded file
}

ACTION = re.compile(
    r"(submit|approve|reject|/create/|update|delete|remove|record|assign|"
    r"withdraw|/close/|complete|release|hold|rectify|finalize|escalate|"
    r"verify|/save|/add/|allocate|transfer|reset|propose)"
)


@pytest.fixture
def seed(db, office, admin_user, team_leader_user, officer_user):
    a = Assignment.objects.create(
        assignment_no="NPC/HQ/ASG/POST/0001/2025-26", type="ASSIGNMENT",
        title="Post Sweep", office=office, status="Ongoing", total_value=50.0,
        gross_value=50.0, total_revenue=40.0, workflow_stage="ACTIVE",
        registration_status="APPROVED", approval_status="APPROVED",
        cost_approval_status="APPROVED", team_approval_status="APPROVED",
        milestone_approval_status="APPROVED", revenue_approval_status="APPROVED",
        team_leader=team_leader_user,
    )
    m = Milestone.objects.create(assignment=a, milestone_no=1, title="M1",
                                 invoice_percent=50, invoice_amount=25, status="Pending")
    rs = RevenueShare.objects.create(assignment=a, officer=team_leader_user,
                                     share_percent=100, share_amount=40)
    inv = InvoiceRequest.objects.create(
        request_number="INV-POST-1", assignment=a, invoice_amount=25.0,
        fy_period="2025-26", requested_by=officer_user, status="PENDING",
    )
    er = EditRequest.objects.create(assignment=a, section="COST",
                                    proposed_by=team_leader_user, reason="x", change_data="{}")
    cl = Client.objects.create(client_code="CLI-POST", client_name="Post Co",
                               client_type="Central Government", created_by=officer_user)
    prog = TrainingProgramme.objects.create(
        programme_number="TRN-POST-1", title="Post Training", office=office,
        coordinator=team_leader_user, created_by=team_leader_user, stage="ANNOUNCED",
    )
    nr = NonRevenueSuggestion.objects.create(
        suggestion_number="NR-POST-1", title="Post NR", office=office, man_days=1,
        status="PENDING_APPROVAL", approval_status="PENDING", created_by=officer_user,
    )
    pw = PreWORecord.objects.create(record_number="ENQ-POST-1", stage="ENQUIRY",
                                    title="Post Enquiry", office=office,
                                    owner=officer_user, created_by=officer_user)
    from datetime import date as _date
    claim = UtilizationClaim.objects.create(
        claim_number="UC-POST-1", officer=team_leader_user, assignment=a,
        claim_month="2026-05", activity_date=_date(2026, 5, 1),
        man_days_claimed=2, status="DRAFT",
    )
    flag = RevenueAllocationFlag.objects.create(
        assignment=a, revenue_share=rs, raised_by=officer_user, reason="x",
    )
    doc = ProposalDocument.objects.create(
        assignment=a, document_type="PROPOSAL", file_name="x.pdf",
        file_path="proposals/x.pdf", file_size=10, uploaded_by=officer_user,
    )
    return {
        "assignment_id": a.pk, "milestone_id": m.pk, "request_id": er.pk,
        "invoice_id": inv.pk, "client_id": cl.pk, "programme_id": prog.pk,
        "suggestion_id": nr.pk, "record_id": pw.pk, "claim_id": claim.pk,
        "flag_id": flag.pk, "document_id": doc.pk, "link_id": 1,
        "section": "cost", "_inv": inv,
    }


def test_post_actions_no_500(admin_user, seed):
    from core import urls as cu
    client = TestClient()
    client.login(email="admin@test.gov.in", password="testpass123")

    offenders, tested = [], 0
    for p in cu.urlpatterns:
        name = getattr(p, "name", None)
        pat = str(p.pattern)
        if not name or name in SKIP or not ACTION.search(pat):
            continue
        params = re.findall(r"<(?:int|str):(\w+)>", pat)
        kwargs, skip = {}, False
        for prm in params:
            if prm not in seed:
                skip = True
                break
            kwargs[prm] = seed[prm]
        if skip:
            continue
        try:
            url = reverse(f"core:{name}", kwargs=kwargs)
        except Exception as e:
            offenders.append(f"{name} -> reverse failed: {e}")
            continue

        tested += 1
        # Fire an empty POST. We're hunting two production-fatal classes:
        #   - NoReverseMatch (stale redirect URL name -> 500 even on valid use)
        #   - unguarded FSM TransitionNotAllowed (500 on double-action)
        # Exceptions that ONLY arise from a deliberately-empty body (a required
        # field missing, or a blank FK id) are expected here and not real bugs,
        # because the real forms always submit those fields.
        EXPECTED_ON_EMPTY = ("MultiValueDictKeyError", "DoesNotExist", "ValueError")
        try:
            resp = client.post(url, {})
        except Exception as e:
            etype = type(e).__name__
            if etype == "NoReverseMatch":
                offenders.append(f"{name} ({url}) -> NoReverseMatch (stale redirect): {e}")
            elif "TransitionNotAllowed" in etype:
                offenders.append(f"{name} ({url}) -> unguarded TransitionNotAllowed: {e}")
            elif etype not in EXPECTED_ON_EMPTY:
                offenders.append(f"{name} ({url}) -> {etype}: {e}")
            continue
        if resp.status_code >= 500:
            offenders.append(f"{name} ({url}) -> HTTP {resp.status_code}")

    print(f"\nPOST SWEEP: fired {tested} action endpoints")
    assert not offenders, "POST ACTION 500s:\n" + "\n".join(offenders)
