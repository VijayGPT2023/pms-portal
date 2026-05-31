"""
Proactive full-page sweep.

Auto-discovers every GET-renderable core URL, fills its params from real
seed objects, and renders it with a strict `string_if_invalid` engine so we
catch — in ONE pass — 500s, NoReverseMatch, blank pages, and invalid template
variables across the whole portal (including parameterized pages like each
assignment-view tab, training programme, client, invoice, etc.).

Action/POST-only endpoints are skipped (they 405 or mutate).
"""
import re

import pytest
from django.test import Client as TestClient

from core.models import (
    Assignment, Client, EditRequest, ExpenditureHead, InvoiceRequest,
    Milestone, NonRevenueSuggestion, Officer, PreWORecord, RevenueShare,
    TrainingProgramme,
)

pytestmark = pytest.mark.django_db

SENTINEL = "XXINVALIDVARXX"

# POST-only / action endpoints that legitimately 302/405 on GET — skip.
SKIP_NAMES = {
    "logout", "update_user_role", "update_training_checklist",
    "training_register_completion", "training_record_payment",
    "revenue_address_flag", "revenue_withdraw_flag",
    "export_assignments", "import_data",
    "health",  # returns JSON, not a template
    "root",    # redirect
}

# "Create"/"new" forms render with a None bound object, so {{ object.field }}
# legitimately resolves empty under the strict harness — that's not a bug.
# We still GET them (must be 200, non-blank) but don't flag invalid vars.
NEW_FORM_NAMES = {"new_client_form", "new_claim_form", "training_create_form",
                  "pre_wo_create_form", "non_revenue_create_form",
                  "change_password_form"}

# Known-safe nullable-FK attribute lookups (e.g. an unallocated officer).
SAFE_VAR_SUFFIXES = (".officer.name", ".item.estimated_amount",
                     ".item.actual_amount", ".item.remarks")

ACTION_RE = re.compile(
    r"(submit|approve|reject|/create/|update|delete|remove|record|assign|"
    r"withdraw|/close/|complete|release|hold|rectify|finalize|escalate|"
    r"verify|/save|logout|/add/|allocate|transfer|reset|/api/|download|/role/)"
)


@pytest.fixture
def seed(db, office, admin_user, team_leader_user, officer_user):
    """One assignment (all sections approved) + every entity a GET param needs."""
    a = Assignment.objects.create(
        assignment_no="NPC/HQ/ASG/SWEEP/0001/2025-26", type="ASSIGNMENT",
        title="Sweep Assignment", client="Test Client", domain="ES",
        office=office, status="Ongoing", total_value=50.0, gross_value=50.0,
        total_revenue=40.0, workflow_stage="ACTIVE", registration_status="APPROVED",
        approval_status="APPROVED", cost_approval_status="APPROVED",
        team_approval_status="APPROVED", milestone_approval_status="APPROVED",
        revenue_approval_status="APPROVED", team_leader=team_leader_user,
    )
    Milestone.objects.create(assignment=a, milestone_no=1, title="M1",
                             invoice_percent=50, invoice_amount=25, status="Pending")
    RevenueShare.objects.create(assignment=a, officer=team_leader_user,
                                share_percent=100, share_amount=40)
    inv = InvoiceRequest.objects.create(
        request_number="INV-SWEEP-1", assignment=a, invoice_amount=25.0,
        fy_period="2025-26", requested_by=officer_user, status="APPROVED",
    )
    head = ExpenditureHead.objects.filter(head_code="A1").first()
    er = EditRequest.objects.create(
        assignment=a, section="COST", proposed_by=team_leader_user,
        reason="sweep", change_data="{}",
    )
    cl = Client.objects.create(client_code="CLI-SWEEP", client_name="Sweep Co",
                               client_type="Central Government", city="Delhi",
                               created_by=officer_user)
    prog = TrainingProgramme.objects.create(
        programme_number="TRN-SWEEP-1", title="Sweep Training", office=office,
        coordinator=team_leader_user, created_by=team_leader_user, stage="ANNOUNCED",
    )
    nr = NonRevenueSuggestion.objects.create(
        suggestion_number="NR-SWEEP-1", title="Sweep NR", office=office,
        man_days=2, status="PENDING_APPROVAL", approval_status="PENDING",
        created_by=officer_user,
    )
    pw = PreWORecord.objects.create(
        record_number="ENQ-SWEEP-1", stage="ENQUIRY", title="Sweep Enquiry",
        office=office, owner=officer_user, created_by=officer_user,
    )
    return {
        "assignment_id": a.pk, "invoice_id": inv.pk, "request_id": er.pk,
        "client_id": cl.pk, "programme_id": prog.pk, "suggestion_id": nr.pk,
        "record_id": pw.pk, "milestone_id": a.milestones.first().pk,
        "flag_id": None, "step_order": 1, "office_id": office.office_id,
        "claim_id": None,  # no claim fixture; edit_claim_form skipped if None
    }


def test_sweep_all_get_pages(admin_user, settings, seed):
    settings.TEMPLATES[0].setdefault("OPTIONS", {})["string_if_invalid"] = SENTINEL + "(%s)"
    from django.template import engines
    engines._engines = {}

    from core import urls as cu
    client = TestClient()
    client.login(email="admin@test.gov.in", password="testpass123")

    offenders = []
    tested = 0
    for p in cu.urlpatterns:
        name = getattr(p, "name", None)
        pat = str(p.pattern)
        if not name or name in SKIP_NAMES or ACTION_RE.search(pat):
            continue
        params = re.findall(r"<(?:int|str):(\w+)>", pat)
        kwargs, skip = {}, False
        for prm in params:
            val = seed.get(prm)
            if val is None:
                skip = True
                break
            kwargs[prm] = val
        if skip:
            continue
        try:
            from django.urls import reverse
            url = reverse(f"core:{name}", kwargs=kwargs)
        except Exception as e:
            offenders.append(f"{name} -> reverse failed: {e}")
            continue

        tested += 1
        resp = client.get(url)
        if resp.status_code not in (200, 302):
            offenders.append(f"{name} ({url}) -> HTTP {resp.status_code}")
            continue
        if resp.status_code == 302:
            continue  # permission redirect etc. — acceptable
        body = resp.content.decode("utf-8", "replace")
        # Blank-page check applies to every page (including new-forms).
        if len(body.strip()) < 200:
            offenders.append(f"{name} ({url}) -> near-empty ({len(body.strip())} chars)")
            continue
        if name in NEW_FORM_NAMES:
            continue  # None bound object -> empty {{ object.field }} is expected
        bad = sorted({
            b for b in re.findall(rf"{SENTINEL}\(([^)]*)\)", body)
            if b.strip() and not b.strip().endswith(SAFE_VAR_SUFFIXES)
        })
        if bad:
            offenders.append(f"{name} ({url}) -> invalid vars: {bad}")

    # Query-param variants the base loop can't reach (tabs, filters, cost-period).
    qp_pages = [
        f"/assignment/view/{seed['assignment_id']}/?tab=basic",
        f"/assignment/view/{seed['assignment_id']}/?tab=milestones",
        f"/assignment/view/{seed['assignment_id']}/?tab=cost",
        f"/assignment/view/{seed['assignment_id']}/?tab=team",
        "/dashboard/?active_tab=physical_progress",
        "/dashboard/?active_tab=financial_progress",
        "/dashboard/?active_tab=business_mis",
        "/non-revenue/?view=pending_approval",
        "/utilization/?view=pending",
        "/pre-wo/?view=pending_approval",
        "/clients/?search=test",
        "/mis/assignments/?sort_by=physical&sort_order=asc",
    ]
    for url in qp_pages:
        tested += 1
        resp = client.get(url)
        if resp.status_code not in (200, 302):
            offenders.append(f"{url} -> HTTP {resp.status_code}")
            continue
        if resp.status_code == 302:
            continue
        body = resp.content.decode("utf-8", "replace")
        if len(body.strip()) < 200:
            offenders.append(f"{url} -> near-empty ({len(body.strip())} chars)")
            continue
        bad = sorted({
            b for b in re.findall(rf"{SENTINEL}\(([^)]*)\)", body)
            if b.strip() and not b.strip().endswith(SAFE_VAR_SUFFIXES)
        })
        if bad:
            offenders.append(f"{url} -> invalid vars: {bad}")

    print(f"\nSWEEP: rendered {tested} GET pages")
    assert not offenders, "PAGE SWEEP FAILURES:\n" + "\n".join(offenders)
