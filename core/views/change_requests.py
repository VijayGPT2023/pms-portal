"""
Change Request views: Officer -> TL -> Head approval flow.
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import ActivityLog, ApprovalRequest, Assignment


def _is_head_or_admin(user):
    """Check if user is admin/head/senior management."""
    return user.admin_role_id in (
        "ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD",
    ) or user.is_staff


@login_required
def change_request_form(request, assignment_id):
    """Display change request form."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    return render(request, "change_requests/form.html", {
        "assignment": assignment,
        "error": request.GET.get("error", ""),
    })


@login_required
def submit_change_request(request, assignment_id):
    """Submit a change request (Officer -> TL for review)."""
    if request.method != "POST":
        return redirect("core:change_request_form", assignment_id=assignment_id)

    assignment = get_object_or_404(Assignment, pk=assignment_id)

    change_type = request.POST.get("change_type", "")
    justification = request.POST.get("justification", "").strip()
    details = request.POST.get("details", "").strip()

    if not change_type or not justification:
        return redirect(
            f"/change-request/new/{assignment_id}?error=Change type and justification are required"
        )

    valid_types = ("MILESTONE_CHANGE", "COST_CHANGE", "TEAM_CHANGE", "REVENUE_CHANGE")
    if change_type not in valid_types:
        return redirect(f"/change-request/new/{assignment_id}?error=Invalid change type")

    request_data = json.dumps({
        "change_type": change_type,
        "details": details,
        "justification": justification,
    })

    ApprovalRequest.objects.create(
        request_type="CHANGE_REQUEST",
        reference_type="assignment",
        reference_id=assignment.pk,
        requested_by=request.user,
        office=assignment.office,
        status="PENDING",
        request_data=request_data,
        remarks=f"{change_type} request by {request.user.name}: {justification[:100]}",
        review_status="PENDING",
    )

    ActivityLog.objects.create(
        actor=request.user,
        action="CREATE",
        entity_type="change_request",
        entity_id=assignment.pk,
        remarks=f"Change request: {change_type}",
    )

    return redirect(f"/assignment/view/{assignment_id}?success=change_request_submitted")


@login_required
def review_change_request(request, request_id):
    """Display change request for TL to review."""
    cr = get_object_or_404(
        ApprovalRequest.objects.select_related("requested_by"),
        pk=request_id,
    )
    try:
        assignment = Assignment.objects.get(pk=cr.reference_id)
    except Assignment.DoesNotExist:
        assignment = None

    return render(request, "change_requests/review.html", {
        "change_request": cr,
        "assignment": assignment,
        "error": request.GET.get("error", ""),
    })


@login_required
def forward_change_request(request, request_id):
    """TL reviews and forwards change request to Head."""
    if request.method != "POST":
        return redirect("core:approvals_list")

    cr = get_object_or_404(ApprovalRequest, pk=request_id)
    cr.review_status = "FORWARDED"
    cr.reviewed_by = request.user.officer_id
    cr.review_notes = request.POST.get("review_notes", "")
    cr.save()

    ActivityLog.objects.create(
        actor=request.user,
        action="UPDATE",
        entity_type="change_request",
        entity_id=cr.reference_id,
        remarks="TL forwarded change request to Head",
    )
    return redirect("core:approvals_list")


@login_required
def tl_reject_change_request(request, request_id):
    """TL rejects the change request."""
    if request.method != "POST":
        return redirect("core:approvals_list")

    cr = get_object_or_404(ApprovalRequest, pk=request_id)
    review_notes = request.POST.get("review_notes", "")
    cr.review_status = "REJECTED"
    cr.status = "REJECTED"
    cr.reviewed_by = request.user.officer_id
    cr.review_notes = review_notes
    cr.approval_remarks = f"Rejected by TL: {review_notes}"
    cr.save()

    ActivityLog.objects.create(
        actor=request.user,
        action="REJECT",
        entity_type="change_request",
        entity_id=cr.reference_id,
        remarks="TL rejected change request",
    )
    return redirect("core:approvals_list")


@login_required
def head_approve_change_request(request, request_id):
    """Head approves a forwarded change request."""
    if request.method != "POST":
        return redirect("core:approvals_list")
    if not _is_head_or_admin(request.user):
        return redirect("/dashboard/?error=unauthorized")

    cr = get_object_or_404(ApprovalRequest, pk=request_id)
    cr.status = "APPROVED"
    cr.approved_by = request.user
    cr.approved_at = timezone.now()
    cr.save()

    # Apply the change: reset the relevant section approval
    try:
        data = json.loads(cr.request_data) if cr.request_data else {}
    except (json.JSONDecodeError, TypeError):
        data = {}

    change_type = data.get("change_type", "")
    reset_map = {
        "MILESTONE_CHANGE": "milestone_approval_status",
        "COST_CHANGE": "cost_approval_status",
        "TEAM_CHANGE": "team_approval_status",
        "REVENUE_CHANGE": "revenue_approval_status",
    }

    if change_type in reset_map:
        try:
            assignment = Assignment.objects.get(pk=cr.reference_id)
            setattr(assignment, reset_map[change_type], "DRAFT")
            assignment.save(update_fields=[reset_map[change_type]])
        except Assignment.DoesNotExist:
            pass

    ActivityLog.objects.create(
        actor=request.user,
        action="APPROVE",
        entity_type="change_request",
        entity_id=cr.reference_id,
        remarks=f"Head approved change request: {change_type}",
    )
    return redirect("core:approvals_list")


@login_required
def head_reject_change_request(request, request_id):
    """Head rejects a forwarded change request."""
    if request.method != "POST":
        return redirect("core:approvals_list")
    if not _is_head_or_admin(request.user):
        return redirect("/dashboard/?error=unauthorized")

    cr = get_object_or_404(ApprovalRequest, pk=request_id)
    cr.status = "REJECTED"
    cr.approval_remarks = request.POST.get("rejection_remarks", "")
    cr.approved_by = request.user
    cr.approved_at = timezone.now()
    cr.save()

    ActivityLog.objects.create(
        actor=request.user,
        action="REJECT",
        entity_type="change_request",
        entity_id=cr.reference_id,
        remarks="Head rejected change request",
    )
    return redirect("core:approvals_list")
