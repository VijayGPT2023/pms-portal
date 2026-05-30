"""
Pre-WO pipeline views (SCOPE_V2 §3.1).

Funnel: Enquiry -> Preliminary Visit -> Proposal -> (converted) Work Order.
- Any Officer creates a record at any stage (no prerequisite stage).
- GH/RD approves.
- Record is closed with an outcome: Converted to WO / Dropped / On Hold.
- Applies to NEW records only.
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import ActivityLog, Assignment, Office, PreWORecord


HEAD_ROLES = ("ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD")
ORG_ROLES = ("ADMIN", "DG", "DDG-I", "DDG-II")

STAGE_PREFIX = {
    "ENQUIRY": "ENQ",
    "PRELIM_VISIT": "PRV",
    "PROPOSAL": "PRP",
}


def _is_head(user):
    return (user.admin_role_id or "") in HEAD_ROLES


def _generate_record_number(stage, office_id):
    today = date.today()
    prefix = f"{STAGE_PREFIX.get(stage, 'PRE')}-{office_id}-{today.strftime('%Y%m')}"
    count = PreWORecord.objects.filter(record_number__startswith=prefix).count()
    return f"{prefix}-{count + 1:03d}"


def _scoped_queryset(user):
    """Org roles see everything; everyone else sees their own office."""
    qs = PreWORecord.objects.select_related("office", "owner", "created_by", "approved_by")
    if (user.admin_role_id or "") in ORG_ROLES:
        return qs
    return qs.filter(office=user.office)


@login_required
def list_records(request):
    """List Pre-WO records with stage/outcome filters and a funnel summary."""
    stage = request.GET.get("stage")
    outcome = request.GET.get("outcome")
    view = request.GET.get("view")

    qs = _scoped_queryset(request.user)
    if stage:
        qs = qs.filter(stage=stage)
    if outcome:
        qs = qs.filter(outcome=outcome)
    if view == "pending_approval" and _is_head(request.user):
        qs = qs.filter(approval_status="PENDING")
    elif view == "mine":
        qs = qs.filter(created_by=request.user)

    qs = qs.order_by("-created_at")

    # Funnel: count approved records per stage + converted count (scoped).
    funnel_base = _scoped_queryset(request.user)
    funnel = {
        "enquiry": funnel_base.filter(stage="ENQUIRY").count(),
        "prelim_visit": funnel_base.filter(stage="PRELIM_VISIT").count(),
        "proposal": funnel_base.filter(stage="PROPOSAL").count(),
        "converted": funnel_base.filter(outcome="CONVERTED_TO_WO").count(),
    }
    pending_count = funnel_base.filter(approval_status="PENDING").count()

    return render(request, "pre_wo/list.html", {
        "records": qs,
        "funnel": funnel,
        "pending_count": pending_count,
        "stages": PreWORecord.Stage.choices,
        "outcomes": PreWORecord.Outcome.choices,
        "filter_stage": stage,
        "filter_outcome": outcome,
        "filter_view": view,
        "is_head": _is_head(request.user),
    })


@login_required
def create_form(request):
    offices = Office.objects.order_by("office_name")
    return render(request, "pre_wo/form.html", {
        "record": None,
        "offices": offices,
        "stages": PreWORecord.Stage.choices,
        "is_new": True,
    })


@login_required
@require_POST
def create_record(request):
    office = Office.objects.get(office_id=request.POST["office_id"])
    stage = request.POST.get("stage", "ENQUIRY")
    if stage not in dict(PreWORecord.Stage.choices):
        stage = "ENQUIRY"

    record = PreWORecord.objects.create(
        record_number=_generate_record_number(stage, office.office_id),
        stage=stage,
        title=request.POST.get("title", "").strip(),
        client=request.POST.get("client", "").strip(),
        description=request.POST.get("description", ""),
        domain=request.POST.get("domain", ""),
        expected_value=float(request.POST.get("expected_value", 0) or 0),
        expected_date=request.POST.get("expected_date") or None,
        office=office,
        owner=request.user,
        created_by=request.user,
    )
    ActivityLog.objects.create(
        actor=request.user, action="CREATE",
        entity_type="pre_wo_record", entity_id=record.pk,
        remarks=f"Pre-WO {record.get_stage_display()} created: {record.record_number}",
    )
    messages.success(request, f"{record.get_stage_display()} {record.record_number} created.")
    return redirect("core:pre_wo_view", record_id=record.pk)


@login_required
def view_record(request, record_id):
    record = get_object_or_404(
        PreWORecord.objects.select_related("office", "owner", "created_by", "approved_by", "converted_assignment"),
        pk=record_id,
    )
    can_approve = _is_head(request.user) and record.approval_status == "PENDING"
    can_edit = (
        record.created_by == request.user and record.approval_status == "PENDING"
    ) or _is_head(request.user)
    # Approved + still open records can be converted/closed.
    can_close = record.approval_status == "APPROVED" and record.outcome == "OPEN" and (
        can_edit or record.owner == request.user
    )
    open_assignments = []
    if can_close:
        open_assignments = (
            Assignment.objects.filter(office=record.office)
            .order_by("-created_at")[:200]
        )
    return render(request, "pre_wo/view.html", {
        "record": record,
        "can_approve": can_approve,
        "can_edit": can_edit,
        "can_close": can_close,
        "open_assignments": open_assignments,
    })


@login_required
def edit_form(request, record_id):
    record = get_object_or_404(PreWORecord, pk=record_id)
    offices = Office.objects.order_by("office_name")
    return render(request, "pre_wo/form.html", {
        "record": record,
        "offices": offices,
        "stages": PreWORecord.Stage.choices,
        "is_new": False,
    })


@login_required
@require_POST
def edit_record(request, record_id):
    record = get_object_or_404(PreWORecord, pk=record_id)
    if not ((record.created_by == request.user and record.approval_status == "PENDING") or _is_head(request.user)):
        messages.error(request, "You cannot edit this record.")
        return redirect("core:pre_wo_view", record_id=record.pk)

    record.title = request.POST.get("title", record.title).strip()
    record.client = request.POST.get("client", record.client).strip()
    record.description = request.POST.get("description", record.description)
    record.domain = request.POST.get("domain", record.domain)
    record.expected_value = float(request.POST.get("expected_value", 0) or 0)
    record.expected_date = request.POST.get("expected_date") or None
    new_stage = request.POST.get("stage", record.stage)
    if new_stage in dict(PreWORecord.Stage.choices):
        record.stage = new_stage
    record.save()

    ActivityLog.objects.create(
        actor=request.user, action="UPDATE",
        entity_type="pre_wo_record", entity_id=record.pk,
        remarks=f"Pre-WO {record.record_number} updated",
    )
    messages.success(request, "Record updated.")
    return redirect("core:pre_wo_view", record_id=record.pk)


@login_required
@require_POST
def approve_record(request, record_id):
    record = get_object_or_404(PreWORecord, pk=record_id)
    if not _is_head(request.user):
        messages.error(request, "Only a Group/Regional Head can approve.")
        return redirect("core:pre_wo_view", record_id=record.pk)
    if record.approval_status != "PENDING":
        messages.error(request, f"Record is already {record.get_approval_status_display()}.")
        return redirect("core:pre_wo_view", record_id=record.pk)

    record.approval_status = "APPROVED"
    record.approved_by = request.user
    record.approved_at = timezone.now()
    record.save(update_fields=["approval_status", "approved_by", "approved_at", "updated_at"])

    ActivityLog.objects.create(
        actor=request.user, action="APPROVE",
        entity_type="pre_wo_record", entity_id=record.pk,
        remarks=f"Pre-WO {record.record_number} approved",
    )
    messages.success(request, f"{record.record_number} approved.")
    return redirect("core:pre_wo_view", record_id=record.pk)


@login_required
@require_POST
def reject_record(request, record_id):
    record = get_object_or_404(PreWORecord, pk=record_id)
    if not _is_head(request.user):
        messages.error(request, "Only a Group/Regional Head can reject.")
        return redirect("core:pre_wo_view", record_id=record.pk)
    if record.approval_status != "PENDING":
        messages.error(request, f"Record is already {record.get_approval_status_display()}.")
        return redirect("core:pre_wo_view", record_id=record.pk)

    reason = (request.POST.get("rejection_reason") or "").strip()
    if not reason:
        messages.error(request, "Rejection reason is required.")
        return redirect("core:pre_wo_view", record_id=record.pk)

    record.approval_status = "REJECTED"
    record.rejection_reason = reason
    record.approved_by = request.user
    record.approved_at = timezone.now()
    record.save(update_fields=["approval_status", "rejection_reason", "approved_by", "approved_at", "updated_at"])

    ActivityLog.objects.create(
        actor=request.user, action="REJECT",
        entity_type="pre_wo_record", entity_id=record.pk,
        remarks=f"Pre-WO {record.record_number} rejected: {reason}",
    )
    messages.success(request, f"{record.record_number} rejected.")
    return redirect("core:pre_wo_view", record_id=record.pk)


@login_required
@require_POST
def close_record(request, record_id):
    """Close an approved record with an outcome: Converted / Dropped / On Hold."""
    record = get_object_or_404(PreWORecord, pk=record_id)
    allowed = _is_head(request.user) or record.created_by == request.user or record.owner == request.user
    if not allowed:
        messages.error(request, "You cannot close this record.")
        return redirect("core:pre_wo_view", record_id=record.pk)
    if record.approval_status != "APPROVED":
        messages.error(request, "Only an approved record can be closed.")
        return redirect("core:pre_wo_view", record_id=record.pk)

    outcome = request.POST.get("outcome")
    if outcome not in dict(PreWORecord.Outcome.choices) or outcome == "OPEN":
        messages.error(request, "Choose a valid outcome.")
        return redirect("core:pre_wo_view", record_id=record.pk)

    record.outcome = outcome
    record.outcome_reason = (request.POST.get("outcome_reason") or "").strip()
    if outcome == "CONVERTED_TO_WO":
        assignment_id = request.POST.get("assignment_id")
        if assignment_id:
            record.converted_assignment = Assignment.objects.filter(pk=assignment_id).first()
    record.save(update_fields=["outcome", "outcome_reason", "converted_assignment", "updated_at"])

    ActivityLog.objects.create(
        actor=request.user, action="UPDATE",
        entity_type="pre_wo_record", entity_id=record.pk,
        remarks=f"Pre-WO {record.record_number} closed: {record.get_outcome_display()}",
    )
    messages.success(request, f"{record.record_number} closed as {record.get_outcome_display()}.")
    return redirect("core:pre_wo_view", record_id=record.pk)
