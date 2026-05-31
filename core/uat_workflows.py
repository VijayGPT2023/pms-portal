"""
Shared multi-role workflow drivers for automated UAT.

Each function drives one lifecycle step *as the correct role*, going through the
real HTTP view (not the ORM) so it exercises auth, permissions, POST parsing,
state transitions and redirects exactly as a browser would. Used by both:
  - tests_django/e2e/test_uat_workflows.py  (asserts every transition)
  - core/management/commands/seed_uat.py    (leaves a browsable populated DB)

A "client" here is a logged-in django.test.Client. Helper `login_as` builds one.
Every driver returns the created/affected object so callers can chain + assert.
"""
from datetime import date

from django.test import Client as TestClient

from core.models import (
    Assignment, Client, InvoiceRequest, Milestone, NonRevenueSuggestion,
    Officer, PreWORecord, RevenueShare, TrainingProgramme, UtilizationClaim,
)


def login_as(email, password="uatpass123"):
    c = TestClient()
    ok = c.login(email=email, password=password)
    assert ok, f"login failed for {email}"
    return c


# ---------------------------------------------------------------------------
# Consultancy lifecycle
# ---------------------------------------------------------------------------

def register_assignment(client, title, office_id, client_name="Test Client",
                        atype="ASSIGNMENT"):
    """Officer/Head registers a new WO -> goes to PENDING_APPROVAL."""
    client.post("/assignment/register/", {
        "type": atype, "title": title, "client": client_name,
        "description": "UAT auto-registered",
    })
    a = Assignment.objects.filter(title=title).order_by("-id").first()
    assert a is not None, f"register failed for {title}"
    return a


def approve_registration(head_client, assignment):
    head_client.post(f"/approvals/registration/{assignment.pk}/approve/", {})
    assignment.refresh_from_db()
    return assignment


def assign_tl(head_client, assignment, tl_officer):
    head_client.post(f"/approvals/allocate-tl/{assignment.pk}/",
                     {"team_leader_id": tl_officer.officer_id})
    assignment.refresh_from_db()
    return assignment


def add_milestone(tl_client, assignment, title="Milestone 1",
                  target="2026-09-30", invoice_percent="100", invoice_amount="50"):
    tl_client.post(f"/assignment/milestones/{assignment.pk}/", {
        "milestone_0_title": title,
        "milestone_0_target_date": target,
        "milestone_0_invoice_percent": invoice_percent,
        "milestone_0_invoice_amount": invoice_amount,
        "next_step": "",
    })
    return list(Milestone.objects.filter(assignment=assignment))


def set_revenue_shares(tl_client, assignment, shares):
    """shares = [(officer, percent), ...] summing to 100."""
    data = {"next_step": ""}
    for i, (off, pct) in enumerate(shares):
        data[f"officer_id_{i}"] = off.officer_id
        data[f"share_percent_{i}"] = str(pct)
    tl_client.post(f"/revenue/edit/{assignment.pk}/submit/", data)
    return list(RevenueShare.objects.filter(assignment=assignment))


def approve_page1(head_client, assignment):
    """Approve the WO-Basic / page-1 section (approval_status). This is the 5th
    section in all_sections_approved(); GH approves it directly (no submit step)."""
    head_client.post(f"/approvals/assignment/{assignment.pk}/approve/", {})
    assignment.refresh_from_db()
    return assignment


def submit_section(tl_client, assignment, section):
    """section in {cost, team, milestone, revenue}."""
    url = {
        "cost": f"/approvals/cost/{assignment.pk}/submit/",
        "team": f"/approvals/team/{assignment.pk}/submit/",
        "milestone": f"/approvals/milestone/{assignment.pk}/submit/",
        "revenue": f"/approvals/revenue/{assignment.pk}/submit/",
    }[section]
    tl_client.post(url, {})
    assignment.refresh_from_db()
    return assignment


def approve_section(head_client, assignment, section):
    url = {
        "cost": f"/approvals/cost/{assignment.pk}/approve/",
        "team": f"/approvals/team/{assignment.pk}/approve/",
        "milestone": f"/approvals/milestone/{assignment.pk}/approve/",
        "revenue": f"/approvals/revenue/{assignment.pk}/approve/",
    }[section]
    head_client.post(url, {})
    assignment.refresh_from_db()
    return assignment


def raise_invoice(client, assignment, amount, fy="2025-26", itype="FINAL"):
    client.post(f"/finance/invoice-request/{assignment.pk}/submit/", {
        "invoice_type": itype, "invoice_amount": str(amount),
        "fy_period": fy, "description": "UAT invoice",
    })
    return InvoiceRequest.objects.filter(assignment=assignment).order_by("-id").first()


def approve_invoice(finance_client, invoice):
    finance_client.post(f"/finance/invoice/{invoice.pk}/approve/", {})
    invoice.refresh_from_db()
    return invoice


def record_payment(finance_client, invoice, amount, when="2026-06-10"):
    finance_client.post(f"/finance/payment/{invoice.pk}/record/", {
        "amount_received": str(amount), "receipt_date": when,
        "payment_mode": "NEFT", "reference_number": "UAT-REF", "remarks": "UAT",
    })
    invoice.refresh_from_db()
    return invoice


# ---------------------------------------------------------------------------
# Pre-WO
# ---------------------------------------------------------------------------

def create_pre_wo(officer_client, title, office_id, stage="ENQUIRY"):
    officer_client.post("/pre-wo/create/submit/", {
        "stage": stage, "title": title, "office_id": office_id,
        "client": "Prospect Co", "expected_value": "500000",
    })
    return PreWORecord.objects.filter(title=title).order_by("-id").first()


def approve_pre_wo(head_client, record):
    head_client.post(f"/pre-wo/{record.pk}/approve/", {})
    record.refresh_from_db()
    return record


def close_pre_wo(client, record, outcome="DROPPED"):
    client.post(f"/pre-wo/{record.pk}/close/", {"outcome": outcome, "outcome_reason": "UAT"})
    record.refresh_from_db()
    return record


# ---------------------------------------------------------------------------
# Non-Revenue
# ---------------------------------------------------------------------------

def create_non_revenue(officer_client, title, office_id, man_days="3"):
    officer_client.post("/non-revenue/create/submit/", {
        "title": title, "activity_type": "RESEARCH", "office_id": office_id,
        "man_days": man_days, "description": "UAT non-revenue task",
    })
    return NonRevenueSuggestion.objects.filter(title=title).order_by("-id").first()


def approve_non_revenue(head_client, nr, officer=None):
    data = {}
    if officer:
        data["officer_id"] = officer.officer_id
    head_client.post(f"/non-revenue/approve/{nr.pk}/", data)
    nr.refresh_from_db()
    return nr


def complete_non_revenue(client, nr):
    client.post(f"/non-revenue/complete/{nr.pk}/", {})
    nr.refresh_from_db()
    return nr


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def create_training(client, title, office_id, participants="30", fee="2000"):
    client.post("/training/create/submit/", {
        "title": title, "office_id": office_id,
        "budgeted_participants": participants, "fee_per_participant": fee,
    })
    return TrainingProgramme.objects.filter(title=title).order_by("-id").first()


def set_faculty(client, programme, faculty):
    """faculty = [(officer, role, percent, days), ...]."""
    data = {}
    for i, (off, role, pct, days) in enumerate(faculty):
        data[f"trainer_{i}_officer_id"] = off.officer_id
        data[f"trainer_{i}_role"] = role
        data[f"trainer_{i}_percent"] = str(pct)
        data[f"trainer_{i}_days"] = str(days)
    client.post(f"/training/trainers/{programme.pk}/submit/", data)
    return programme


def register_completion(client, programme, invoice_amount, expenditure="0",
                        participants="28"):
    client.post(f"/training/{programme.pk}/register-completion/", {
        "actual_participants": participants, "actual_expenditure": str(expenditure),
        "invoice_number": "UAT/TRN/INV", "invoice_amount": str(invoice_amount),
        "invoice_date": "2026-05-20",
    })
    programme.refresh_from_db()
    return programme


def record_training_payment(client, programme, amount):
    client.post(f"/training/{programme.pk}/record-payment/", {
        "payment_amount": str(amount), "payment_date": "2026-06-10",
    })
    programme.refresh_from_db()
    return programme


# ---------------------------------------------------------------------------
# Utilization
# ---------------------------------------------------------------------------

def create_claim(officer_client, assignment, man_days="5", when="2026-05-01"):
    officer_client.post("/utilization/new/submit/", {
        "claim_type": "ASSIGNMENT", "activity_date": when,
        "man_days_claimed": man_days, "assignment_id": str(assignment.pk),
        "activity_description": "UAT claim",
    })
    return UtilizationClaim.objects.filter(assignment=assignment).order_by("-id").first()


def submit_claim(officer_client, claim):
    officer_client.post(f"/utilization/{claim.pk}/submit/", {})
    claim.refresh_from_db()
    return claim


def tl_approve_claim(tl_client, claim):
    tl_client.post(f"/utilization/{claim.pk}/tl-approve/", {"remarks": "ok"})
    claim.refresh_from_db()
    return claim


def head_rectify_claim(head_client, claim, days):
    head_client.post(f"/utilization/{claim.pk}/head-rectify/",
                     {"rectified_days": str(days), "remarks": "adjusted"})
    claim.refresh_from_db()
    return claim


def finalize_claim(head_client, claim):
    head_client.post(f"/utilization/{claim.pk}/finalize/", {})
    claim.refresh_from_db()
    return claim
