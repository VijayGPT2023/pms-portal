"""
Finance views: Invoice requests and payment tracking.
Manages 80-20 revenue recognition workflow.

Revenue Recognition Model (Case Basis):
    - 80% of invoice amount recognized when invoice is APPROVED
    - 20% of payment amount recognized when payment RECEIPT is recorded

Ported from FastAPI finance_routes.py (12 endpoints) to Django views.
"""
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Case, Count, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_fsm import TransitionNotAllowed

from core.models import (
    ActivityLog,
    Assignment,
    AssignmentTeam,
    FinanceOfficer,
    InvoiceMilestoneLink,
    InvoiceRequest,
    Milestone,
    Office,
    Officer,
    OfficerRevenueLedger,
    PaymentReceipt,
    RevenueShare,
)

__all__ = [
    "finance_dashboard",
    "invoice_request_form",
    "submit_invoice_request",
    "approve_invoice_request",
    "reject_invoice_request",
    "payment_form",
    "record_payment",
    "officer_request_invoice",
    "tl_verify_invoice",
    "finance_officer_dashboard",
    "hold_revenue",
    "release_revenue",
]


# ============================================================
# Role-checking helpers
# ============================================================

ADMIN_FINANCE_ROLES = {"ADMIN", "FINANCE", "ACCOUNTS", "DG", "DDG", "DDG-I", "DDG-II"}
SENIOR_ROLES = {"ADMIN", "DG", "DDG-I", "DDG-II"}
HEAD_ROLES = {"RD_HEAD", "GROUP_HEAD"}


def _is_finance_officer(user):
    """Check if user has Finance role (admin_role_id or FinanceOfficer table)."""
    role = (user.admin_role_id or "").upper()
    if role in ADMIN_FINANCE_ROLES:
        return True
    return FinanceOfficer.objects.filter(
        officer_id=user.officer_id,
        is_active=True,
    ).exists()


def _is_admin(user):
    return (user.admin_role_id or "").upper() in SENIOR_ROLES


def _is_head(user):
    return (user.admin_role_id or "").upper() in (SENIOR_ROLES | HEAD_ROLES)


def _log_activity(user, action, entity_type, entity_id, remarks="", new_data=""):
    ActivityLog.objects.create(
        actor_id=user.officer_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        new_data=new_data,
        remarks=remarks,
    )


def _get_current_fy(ref_date=None):
    """Return current financial year string, e.g. '2025-26'."""
    d = ref_date or date.today()
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    return f"{d.year - 1}-{str(d.year)[2:]}"


def _generate_invoice_request_number(office_id):
    """Generate unique invoice request number: INV-OFFICE-YYYYMM-NNN."""
    today = date.today()
    prefix = f"INV-{office_id}-{today.strftime('%Y%m')}"
    count = InvoiceRequest.objects.filter(
        request_number__startswith=prefix
    ).count()
    return f"{prefix}-{count + 1:03d}"


def _generate_receipt_number(office_id):
    """Generate unique receipt number: RCP-OFFICE-YYYYMM-NNN."""
    today = date.today()
    prefix = f"RCP-{office_id}-{today.strftime('%Y%m')}"
    count = PaymentReceipt.objects.filter(
        receipt_number__startswith=prefix
    ).count()
    return f"{prefix}-{count + 1:03d}"


# ============================================================
# Finance Dashboard (Admin / Global Finance)
# ============================================================

@login_required
def finance_dashboard(request):
    """Display Finance dashboard with pending invoices."""
    if not _is_finance_officer(request.user):
        messages.error(request, "You do not have finance access.")
        return redirect("core:dashboard")

    # Pending invoice requests
    pending_invoices = (
        InvoiceRequest.objects
        .filter(status="PENDING")
        .select_related("assignment", "requested_by", "milestone")
        .order_by("-created_at")
    )

    # Recently approved invoices
    approved_invoices = (
        InvoiceRequest.objects
        .filter(status__in=["APPROVED", "INVOICED"])
        .select_related("assignment", "requested_by", "approved_by")
        .order_by("-approved_at")[:20]
    )

    # Summary stats
    stats = InvoiceRequest.objects.aggregate(
        pending_count=Count("id", filter=Q(status="PENDING")),
        approved_count=Count("id", filter=Q(status="APPROVED")),
        pending_value=Coalesce(
            Sum("invoice_amount", filter=Q(status="PENDING")),
            0.0,
        ),
        approved_value=Coalesce(
            Sum("invoice_amount", filter=Q(status="APPROVED")),
            0.0,
        ),
    )

    return render(request, "finance/finance_dashboard.html", {
        "pending_invoices": pending_invoices,
        "approved_invoices": approved_invoices,
        "stats": stats,
    })


# ============================================================
# Invoice Request Form (GET) + Submit (POST)
# ============================================================

@login_required
def invoice_request_form(request, assignment_id):
    """Display invoice request form for TL."""
    assignment = get_object_or_404(
        Assignment.objects.select_related("team_leader"),
        pk=assignment_id,
    )

    # Verify user is TL or head/admin
    if assignment.team_leader:
        if assignment.team_leader.officer_id != request.user.officer_id:
            if not (_is_admin(request.user) or _is_head(request.user)):
                messages.error(request, "Only the team leader can request invoices.")
                return redirect("core:dashboard")

    milestones = Milestone.objects.filter(
        assignment=assignment
    ).order_by("milestone_no")

    existing_requests = (
        InvoiceRequest.objects
        .filter(assignment=assignment)
        .select_related("milestone")
        .order_by("-created_at")
    )

    # Calculate remaining value to invoice
    total_invoiced = (
        InvoiceRequest.objects
        .filter(assignment=assignment)
        .exclude(status="REJECTED")
        .aggregate(total=Coalesce(Sum("invoice_amount"), 0.0))["total"]
    )
    total_value = assignment.total_value or assignment.gross_value or 0
    remaining = total_value - total_invoiced

    selected_milestone_id = request.GET.get("milestone_id")
    if selected_milestone_id:
        try:
            selected_milestone_id = int(selected_milestone_id)
        except (ValueError, TypeError):
            selected_milestone_id = None

    return render(request, "finance/invoice_request_form.html", {
        "assignment": assignment,
        "milestones": milestones,
        "existing_requests": existing_requests,
        "selected_milestone_id": selected_milestone_id,
        "remaining_value": remaining,
        "total_invoiced": total_invoiced,
        "current_fy": _get_current_fy(),
    })


@login_required
@require_POST
def submit_invoice_request(request, assignment_id):
    """TL submits invoice request for Finance approval.

    Supports multi-milestone invoices via milestone_ids and milestone_amounts.
    Legacy single milestone_id is also supported.
    """
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Verify user is TL or head/admin
    if assignment.team_leader:
        if assignment.team_leader.officer_id != request.user.officer_id:
            if not (_is_admin(request.user) or _is_head(request.user)):
                messages.error(request, "Unauthorized.")
                return redirect("core:dashboard")

    invoice_amount = float(request.POST.get("invoice_amount", 0))
    invoice_type = request.POST.get("invoice_type", "SUBSEQUENT")
    milestone_id = request.POST.get("milestone_id") or None
    milestone_ids = request.POST.get("milestone_ids", "")
    milestone_amounts = request.POST.get("milestone_amounts", "")
    fy_period = request.POST.get("fy_period", _get_current_fy())
    description = request.POST.get("description", "")

    if milestone_id:
        try:
            milestone_id = int(milestone_id)
        except (ValueError, TypeError):
            milestone_id = None

    office_id = assignment.office.office_id
    request_number = _generate_invoice_request_number(office_id)

    with transaction.atomic():
        inv_req = InvoiceRequest.objects.create(
            request_number=request_number,
            assignment=assignment,
            milestone_id=milestone_id,
            invoice_type=invoice_type,
            invoice_amount=invoice_amount,
            fy_period=fy_period,
            description=description,
            status="PENDING",
            requested_by=request.user,
            officer_request_status="DIRECT",
        )

        # Feature 4A: Link multiple milestones if provided
        if milestone_ids and milestone_amounts:
            m_ids = [mid.strip() for mid in milestone_ids.split(",") if mid.strip()]
            m_amts = [ma.strip() for ma in milestone_amounts.split(",") if ma.strip()]

            if len(m_ids) == len(m_amts):
                for mid_str, mamt_str in zip(m_ids, m_amts):
                    try:
                        mid = int(mid_str)
                        mamt = float(mamt_str)
                        rev_pct = (mamt / invoice_amount * 100) if invoice_amount > 0 else 0

                        milestone_obj = Milestone.objects.filter(pk=mid).first()
                        ms_date = milestone_obj.target_date if milestone_obj else None

                        InvoiceMilestoneLink.objects.create(
                            invoice_request=inv_req,
                            milestone_id=mid,
                            milestone_share_amount=mamt,
                            revenue_share_percent=rev_pct,
                            milestone_date=ms_date,
                        )
                    except (ValueError, TypeError):
                        continue

        _log_activity(
            request.user, "CREATE", "invoice_request", assignment_id,
            "Invoice request submitted",
            new_data=f"amount={invoice_amount}, type={invoice_type}",
        )

    messages.success(request, f"Invoice request {request_number} submitted.")
    return redirect("core:invoice_request_form", assignment_id=assignment_id)


# ============================================================
# Invoice Approve / Reject (Finance)
# ============================================================

@login_required
@require_POST
def approve_invoice_request(request, request_id):
    """Finance approves invoice request.

    Triggers 80% revenue recognition and creates officer revenue ledger entries.
    Feature 3H: Requires TL verification for officer-initiated requests.
    """
    if not _is_finance_officer(request.user):
        messages.error(request, "Only finance officers can approve invoices.")
        return redirect("core:dashboard")

    inv_req = get_object_or_404(
        InvoiceRequest.objects.select_related("assignment"),
        pk=request_id,
    )

    # Feature 3H: Require TL verification for officer-initiated requests
    officer_request_status = inv_req.officer_request_status or "DIRECT"
    if officer_request_status == "OFFICER_REQUESTED":
        messages.error(request, "This invoice needs TL verification first.")
        return redirect("core:finance_dashboard")

    if inv_req.status != "PENDING":
        messages.error(request, f"Invoice is already {inv_req.status} — cannot approve.")
        return redirect("core:finance_dashboard")

    with transaction.atomic():
        # Use django-fsm transition (auto-calculates revenue_recognized_80)
        try:
            inv_req.approve()
        except TransitionNotAllowed:
            messages.error(request, "Invoice cannot be approved from its current state.")
            return redirect("core:finance_dashboard")
        inv_req.approved_by = request.user
        inv_req.approved_at = timezone.now()
        inv_req.save()

        revenue_80 = inv_req.revenue_recognized_80
        tl_revenue_hold = inv_req.tl_revenue_hold

        # Update milestone if linked (single milestone -- legacy)
        if inv_req.milestone_id:
            Milestone.objects.filter(pk=inv_req.milestone_id).update(
                invoice_raised=True,
                invoice_raised_date=date.today(),
                invoice_amount=inv_req.invoice_amount,
            )

        # Feature 4A: Update milestones linked via invoice_milestone_links
        linked_milestones = InvoiceMilestoneLink.objects.filter(
            invoice_request=inv_req
        )
        for lm in linked_milestones:
            Milestone.objects.filter(pk=lm.milestone_id).update(
                invoice_raised=True,
                invoice_raised_date=date.today(),
                invoice_amount=F("invoice_amount") + lm.milestone_share_amount,
            )

        # Update assignment invoice tracking
        Assignment.objects.filter(pk=inv_req.assignment_id).update(
            invoice_amount=F("invoice_amount") + inv_req.invoice_amount,
        )

        # Create revenue ledger entries for 80% recognition
        shares = RevenueShare.objects.filter(assignment_id=inv_req.assignment_id)
        for share in shares:
            officer_revenue = revenue_80 * (share.share_percent / 100)
            OfficerRevenueLedger.objects.create(
                officer_id=share.officer_id,
                assignment_id=inv_req.assignment_id,
                invoice_request=inv_req,
                revenue_type="INVOICE_80",
                share_percent=share.share_percent,
                amount=officer_revenue,
                fy_period=inv_req.fy_period,
                transaction_date=date.today(),
                is_held=bool(tl_revenue_hold),
                remarks="80% revenue on invoice approval",
            )

        _log_activity(
            request.user, "APPROVE", "invoice_request", request_id,
            "Invoice approved, 80% revenue recognized"
        )

    messages.success(request, "Invoice approved. 80% revenue recognized.")
    return redirect("core:finance_dashboard")


@login_required
@require_POST
def reject_invoice_request(request, request_id):
    """Finance rejects invoice request."""
    if not _is_finance_officer(request.user):
        messages.error(request, "Only finance officers can reject invoices.")
        return redirect("core:dashboard")

    rejection_remarks = request.POST.get("rejection_remarks", "")
    inv_req = get_object_or_404(InvoiceRequest, pk=request_id)

    if inv_req.status != "PENDING":
        messages.error(request, f"Invoice is already {inv_req.status} — cannot reject.")
        return redirect("core:finance_dashboard")
    try:
        inv_req.reject()
    except TransitionNotAllowed:
        messages.error(request, "Invoice cannot be rejected from its current state.")
        return redirect("core:finance_dashboard")
    inv_req.approved_by = request.user
    inv_req.approved_at = timezone.now()
    inv_req.approval_remarks = rejection_remarks
    inv_req.save()

    _log_activity(
        request.user, "REJECT", "invoice_request", request_id,
        rejection_remarks
    )
    messages.success(request, "Invoice request rejected.")
    return redirect("core:finance_dashboard")


# ============================================================
# Payment Form (GET) + Record Payment (POST)
# ============================================================

@login_required
def payment_form(request, invoice_id):
    """Display payment recording form."""
    if not _is_finance_officer(request.user):
        messages.error(request, "Only finance officers can record payments.")
        return redirect("core:dashboard")

    invoice = get_object_or_404(
        InvoiceRequest.objects.select_related("assignment", "requested_by"),
        pk=invoice_id,
    )

    payments = PaymentReceipt.objects.filter(
        invoice_request=invoice
    ).order_by("-receipt_date")

    total_paid = sum(p.amount_received for p in payments)
    remaining = (invoice.invoice_amount or 0) - total_paid

    return render(request, "finance/payment_form.html", {
        "invoice": invoice,
        "payments": payments,
        "total_paid": total_paid,
        "remaining": remaining,
    })


@login_required
@require_POST
def record_payment(request, invoice_id):
    """Record payment receipt -- triggers 20% revenue recognition.

    Revenue is recognized on a CASE basis -- triggered by recording the
    payment receipt event, not by any time-based schedule.
    """
    if not _is_finance_officer(request.user):
        messages.error(request, "Only finance officers can record payments.")
        return redirect("core:dashboard")

    invoice = get_object_or_404(
        InvoiceRequest.objects.select_related("assignment"),
        pk=invoice_id,
    )

    amount_received = float(request.POST.get("amount_received", 0))
    receipt_date_str = request.POST.get("receipt_date", "")
    payment_mode = request.POST.get("payment_mode", "")
    reference_number = request.POST.get("reference_number", "")
    remarks = request.POST.get("remarks", "")

    try:
        receipt_dt = datetime.strptime(receipt_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        receipt_dt = date.today()

    fy = _get_current_fy(receipt_dt)
    office_id = invoice.assignment.office.office_id
    receipt_number = _generate_receipt_number(office_id)

    with transaction.atomic():
        # PaymentReceipt.save() auto-calculates revenue_recognized_20
        payment = PaymentReceipt.objects.create(
            receipt_number=receipt_number,
            invoice_request=invoice,
            amount_received=amount_received,
            receipt_date=receipt_dt,
            payment_mode=payment_mode,
            reference_number=reference_number,
            fy_period=fy,
            remarks=remarks,
            updated_by=request.user,
        )

        revenue_20 = payment.revenue_recognized_20

        # Update milestone if linked
        if invoice.milestone_id:
            Milestone.objects.filter(pk=invoice.milestone_id).update(
                payment_received=True,
                payment_received_date=receipt_dt,
                status="Completed",
            )

        # Update assignment payment tracking
        Assignment.objects.filter(pk=invoice.assignment_id).update(
            amount_received=F("amount_received") + amount_received,
        )

        # Create revenue ledger entries for 20% recognition
        shares = RevenueShare.objects.filter(
            assignment_id=invoice.assignment_id
        )
        for share in shares:
            officer_revenue = revenue_20 * (share.share_percent / 100)
            OfficerRevenueLedger.objects.create(
                officer_id=share.officer_id,
                assignment_id=invoice.assignment_id,
                invoice_request=invoice,
                payment_receipt=payment,
                revenue_type="PAYMENT_20",
                share_percent=share.share_percent,
                amount=officer_revenue,
                fy_period=fy,
                transaction_date=receipt_dt,
                remarks="20% revenue on payment receipt",
            )

        _log_activity(
            request.user, "CREATE", "payment_receipt", invoice_id,
            "Payment recorded, 20% revenue recognized",
            new_data=f"amount={amount_received}, mode={payment_mode}",
        )

    messages.success(
        request,
        f"Payment of {amount_received:.2f}L recorded. "
        f"20% revenue ({revenue_20:.2f}L) recognized."
    )
    return redirect("core:payment_form", invoice_id=invoice_id)


# ============================================================
# Feature 3H: Officer Invoice Request -> TL Verify -> Finance
# ============================================================

@login_required
@require_POST
def officer_request_invoice(request, assignment_id):
    """Officer requests an invoice (Feature 3H flow).

    Officer fills in details -> status = OFFICER_REQUESTED -> PENDING.
    Then TL verifies, Head approves, Finance processes.
    Supports Feature 4A multi-milestone invoices.
    """
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    officer_id = request.user.officer_id

    # Officer must be on the team or be TL
    is_tl = (
        assignment.team_leader
        and assignment.team_leader.officer_id == officer_id
    )
    is_team = AssignmentTeam.objects.filter(
        assignment=assignment,
        officer_id=officer_id,
        is_active=True,
    ).exists()

    if not is_tl and not is_team and not _is_admin(request.user):
        messages.error(request, "You must be on the assignment team.")
        return redirect("core:dashboard")

    invoice_amount = float(request.POST.get("invoice_amount", 0))
    invoice_type = request.POST.get("invoice_type", "SUBSEQUENT")
    milestone_ids = request.POST.get("milestone_ids", "")
    milestone_amounts = request.POST.get("milestone_amounts", "")
    fy_period = request.POST.get("fy_period", _get_current_fy())
    description = request.POST.get("description", "")

    office_id = assignment.office.office_id
    request_number = _generate_invoice_request_number(office_id)

    with transaction.atomic():
        inv_req = InvoiceRequest.objects.create(
            request_number=request_number,
            assignment=assignment,
            invoice_type=invoice_type,
            invoice_amount=invoice_amount,
            fy_period=fy_period,
            description=description,
            status="PENDING",
            requested_by=request.user,
            officer_request_status="OFFICER_REQUESTED",
            requested_by_officer_id=officer_id,
        )

        # Feature 4A: Link multiple milestones
        if milestone_ids and milestone_amounts:
            m_ids = [mid.strip() for mid in milestone_ids.split(",") if mid.strip()]
            m_amts = [ma.strip() for ma in milestone_amounts.split(",") if ma.strip()]

            if len(m_ids) == len(m_amts):
                total_ms_amount = 0.0
                for mid_str, mamt_str in zip(m_ids, m_amts):
                    try:
                        mid = int(mid_str)
                        mamt = float(mamt_str)
                        total_ms_amount += mamt
                        rev_pct = (mamt / invoice_amount * 100) if invoice_amount > 0 else 0

                        milestone_obj = Milestone.objects.filter(pk=mid).first()
                        ms_date = milestone_obj.target_date if milestone_obj else None

                        InvoiceMilestoneLink.objects.create(
                            invoice_request=inv_req,
                            milestone_id=mid,
                            milestone_share_amount=mamt,
                            revenue_share_percent=rev_pct,
                            milestone_date=ms_date,
                        )
                    except (ValueError, TypeError):
                        continue

                # Warn if amounts do not match
                if abs(total_ms_amount - invoice_amount) > 0.01:
                    _log_activity(
                        request.user, "CREATE", "invoice_request", inv_req.pk,
                        "Milestone amounts sum mismatch with invoice amount"
                    )

        _log_activity(
            request.user, "CREATE", "invoice_request", assignment_id,
            "Officer requested invoice (Feature 3H)",
            new_data=f"amount={invoice_amount}, type={invoice_type}, officer_requested=1",
        )

    messages.success(request, f"Invoice request {request_number} submitted for TL verification.")
    return redirect("core:invoice_request_form", assignment_id=assignment_id)


@login_required
@require_POST
def tl_verify_invoice(request, request_id):
    """TL verifies an officer-initiated invoice request.

    Feature 3H: Only TL of the assignment can verify.
    Changes officer_request_status from OFFICER_REQUESTED to TL_VERIFIED.
    """
    inv_req = get_object_or_404(
        InvoiceRequest.objects.select_related("assignment", "assignment__team_leader"),
        pk=request_id,
    )

    # Only TL of the assignment (or admin) can verify
    assignment = inv_req.assignment
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_admin(request.user):
            messages.error(request, "Only the team leader can verify this request.")
            return redirect("core:dashboard")

    # Must be in OFFICER_REQUESTED status
    if (inv_req.officer_request_status or "DIRECT") != "OFFICER_REQUESTED":
        messages.error(request, "This request is not awaiting TL verification.")
        return redirect("core:invoice_request_form", assignment_id=assignment.pk)

    inv_req.officer_request_status = "TL_VERIFIED"
    inv_req.verified_by = request.user
    inv_req.verified_at = timezone.now()
    inv_req.save()

    _log_activity(
        request.user, "CREATE", "invoice_request", request_id,
        "TL verified officer invoice request (Feature 3H)"
    )
    messages.success(request, "Invoice request verified.")
    return redirect("core:invoice_request_form", assignment_id=assignment.pk)


# ============================================================
# Finance Officer Dashboard (Office-scoped)
# ============================================================

@login_required
def finance_officer_dashboard(request):
    """Finance Officer dashboard showing pending invoices for managed offices.

    Feature 3H: Uses finance_officers table to determine which offices
    the current finance officer manages.
    """
    if not _is_finance_officer(request.user) and not _is_admin(request.user):
        messages.error(request, "You do not have finance access.")
        return redirect("core:dashboard")

    officer_id = request.user.officer_id

    # Get offices this finance officer manages
    managed_offices = list(
        FinanceOfficer.objects
        .filter(officer_id=officer_id, is_active=True)
        .select_related("office")
        .values("office__office_id", "office__office_name")
    )
    managed_office_ids = [mo["office__office_id"] for mo in managed_offices]

    # If admin with no specific offices, show all
    if _is_admin(request.user) and not managed_office_ids:
        managed_office_ids = list(
            Office.objects.values_list("office_id", flat=True)
        )

    empty_ctx = {
        "managed_offices": managed_offices,
        "pending_invoices": [],
        "officer_requested_invoices": [],
        "tl_verified_invoices": [],
        "approved_invoices": [],
        "stats": {
            "pending_count": 0,
            "officer_requested_count": 0,
            "tl_verified_count": 0,
            "approved_count": 0,
            "pending_value": 0,
            "approved_value": 0,
        },
    }

    if not managed_office_ids:
        return render(request, "finance/finance_officer_dashboard.html", empty_ctx)

    office_q = Q(assignment__office__office_id__in=managed_office_ids)

    # Ready for finance approval (DIRECT or TL_VERIFIED)
    pending_invoices = (
        InvoiceRequest.objects
        .filter(
            office_q,
            status="PENDING",
        )
        .filter(
            Q(officer_request_status__in=["DIRECT", "TL_VERIFIED"])
            | Q(officer_request_status__isnull=True)
            | Q(officer_request_status="")
        )
        .select_related("assignment", "requested_by", "milestone")
        .order_by("-created_at")
    )

    # Officer-requested (awaiting TL verification)
    officer_requested_invoices = (
        InvoiceRequest.objects
        .filter(
            office_q,
            status="PENDING",
            officer_request_status="OFFICER_REQUESTED",
        )
        .select_related("assignment", "requested_by")
        .order_by("-created_at")
    )

    # TL-verified (awaiting head/finance approval)
    tl_verified_invoices = (
        InvoiceRequest.objects
        .filter(
            office_q,
            status="PENDING",
            officer_request_status="TL_VERIFIED",
        )
        .select_related("assignment", "requested_by", "verified_by")
        .order_by("-created_at")
    )

    # Recently approved
    approved_invoices = (
        InvoiceRequest.objects
        .filter(
            office_q,
            status__in=["APPROVED", "INVOICED"],
        )
        .select_related("assignment", "requested_by", "approved_by")
        .order_by("-approved_at")[:20]
    )

    # Summary stats
    base_qs = InvoiceRequest.objects.filter(office_q)
    stats = base_qs.aggregate(
        pending_count=Count(
            "id",
            filter=Q(status="PENDING") & (
                Q(officer_request_status__in=["DIRECT", "TL_VERIFIED"])
                | Q(officer_request_status__isnull=True)
                | Q(officer_request_status="")
            ),
        ),
        officer_requested_count=Count(
            "id",
            filter=Q(status="PENDING", officer_request_status="OFFICER_REQUESTED"),
        ),
        tl_verified_count=Count(
            "id",
            filter=Q(status="PENDING", officer_request_status="TL_VERIFIED"),
        ),
        approved_count=Count(
            "id",
            filter=Q(status="APPROVED"),
        ),
        pending_value=Coalesce(
            Sum("invoice_amount", filter=Q(status="PENDING")),
            0.0,
        ),
        approved_value=Coalesce(
            Sum("invoice_amount", filter=Q(status="APPROVED")),
            0.0,
        ),
    )

    return render(request, "finance/finance_officer_dashboard.html", {
        "managed_offices": managed_offices,
        "pending_invoices": pending_invoices,
        "officer_requested_invoices": officer_requested_invoices,
        "tl_verified_invoices": tl_verified_invoices,
        "approved_invoices": approved_invoices,
        "stats": stats,
    })


# ============================================================
# Feature 4A: TL Revenue Hold / Release
# ============================================================

@login_required
@require_POST
def hold_revenue(request, request_id):
    """TL places a revenue hold on an invoice.

    Feature 4A: TL can mark tl_revenue_hold = True on an invoice.
    When revenue is allocated, ledger entries are marked with is_held=True.
    """
    inv_req = get_object_or_404(
        InvoiceRequest.objects.select_related("assignment", "assignment__team_leader"),
        pk=request_id,
    )

    # Only TL of the assignment (or admin) can hold
    assignment = inv_req.assignment
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_admin(request.user):
            messages.error(request, "Only the team leader can place a revenue hold.")
            return redirect("core:dashboard")

    with transaction.atomic():
        inv_req.tl_revenue_hold = True
        inv_req.save(update_fields=["tl_revenue_hold", "updated_at"])

        # If revenue was already allocated, mark existing ledger entries as held
        OfficerRevenueLedger.objects.filter(
            invoice_request=inv_req,
            revenue_type="INVOICE_80",
        ).update(is_held=True)

    _log_activity(
        request.user, "CREATE", "invoice_request", request_id,
        "TL placed revenue hold on invoice (Feature 4A)"
    )
    messages.success(request, "Revenue hold placed on this invoice.")
    return redirect("core:invoice_request_form", assignment_id=assignment.pk)


@login_required
@require_POST
def release_revenue(request, request_id):
    """TL releases a revenue hold on an invoice.

    Feature 4A: If milestone_release_percents is provided (comma-separated
    milestone_id:percent pairs), TL can specify partial release. Otherwise
    releases all held revenue at 100%.
    """
    inv_req = get_object_or_404(
        InvoiceRequest.objects.select_related("assignment", "assignment__team_leader"),
        pk=request_id,
    )

    # Only TL (or admin)
    assignment = inv_req.assignment
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_admin(request.user):
            messages.error(request, "Only the team leader can release revenue.")
            return redirect("core:dashboard")

    milestone_release_percents = request.POST.get("milestone_release_percents", "")

    with transaction.atomic():
        inv_req.tl_revenue_hold = False
        inv_req.save(update_fields=["tl_revenue_hold", "updated_at"])

        if milestone_release_percents:
            # Parse milestone:percent pairs
            pairs = [p.strip() for p in milestone_release_percents.split(",") if p.strip()]
            total_release_pct = 0.0
            for pair in pairs:
                try:
                    parts = pair.split(":")
                    if len(parts) == 2:
                        release_pct = float(parts[1])
                        total_release_pct += release_pct
                except (ValueError, TypeError):
                    continue

            if total_release_pct > 0:
                held_entries = OfficerRevenueLedger.objects.filter(
                    invoice_request=inv_req,
                    is_held=True,
                )
                release_fraction = min(total_release_pct / 100.0, 1.0)

                for entry in held_entries:
                    if release_fraction >= 1.0:
                        # Full release
                        entry.is_held = False
                        entry.released_by = request.user.officer_id
                        entry.released_at = timezone.now()
                        entry.save()
                    else:
                        # Partial release: reduce held amount, create released entry
                        original_amount = entry.amount
                        released_amount = original_amount * release_fraction
                        remaining_held = original_amount - released_amount

                        # Update existing entry to remaining held amount
                        entry.amount = remaining_held
                        entry.save()

                        # Create new entry for released portion
                        OfficerRevenueLedger.objects.create(
                            officer_id=entry.officer_id,
                            assignment_id=entry.assignment_id,
                            invoice_request=entry.invoice_request,
                            revenue_type="INVOICE_80",
                            share_percent=entry.share_percent,
                            amount=released_amount,
                            fy_period=entry.fy_period,
                            transaction_date=entry.transaction_date,
                            is_held=False,
                            released_by=request.user.officer_id,
                            released_at=timezone.now(),
                            remarks="Partial release by TL",
                        )
        else:
            # Full release of all held entries
            OfficerRevenueLedger.objects.filter(
                invoice_request=inv_req,
                is_held=True,
            ).update(
                is_held=False,
                released_by=request.user.officer_id,
                released_at=timezone.now(),
            )

    _log_activity(
        request.user, "CREATE", "invoice_request", request_id,
        "TL released revenue hold (Feature 4A)"
    )
    messages.success(request, "Revenue hold released.")
    return redirect("core:invoice_request_form", assignment_id=assignment.pk)
