"""
Approval workflow views for managing assignment approvals, section approvals,
team allocations, and change requests.

Ported from FastAPI approval_routes.py (23 endpoints) to Django views.
Uses Django ORM with django-fsm state machine transitions.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import (
    ActivityLog,
    ApprovalRequest,
    Assignment,
    AssignmentTeam,
    ExpenditureItem,
    InvoiceRequest,
    Milestone,
    Officer,
    OfficerRole,
    RevenueShare,
)

__all__ = [
    "approvals_page",
    "approve_registration",
    "reject_registration",
    "approve_assignment",
    "reject_assignment",
    "allocate_team_leader",
    "approve_request",
    "reject_request",
    "escalate_request",
    "submit_cost_estimation",
    "approve_cost_estimation",
    "reject_cost_estimation",
    "submit_team_constitution",
    "approve_team_constitution",
    "reject_team_constitution",
    "submit_milestone_planning",
    "approve_milestone_planning",
    "reject_milestone_planning",
    "submit_revenue_shares",
    "approve_revenue_shares",
    "reject_revenue_shares",
    "approve_tentative_date",
    "reject_tentative_date",
]

# ============================================================
# Role-checking helpers
# ============================================================

SENIOR_ROLES = {"ADMIN", "DG", "DDG-I", "DDG-II"}
HEAD_ROLES = {"RD_HEAD", "GROUP_HEAD"}
APPROVER_ROLES = SENIOR_ROLES | HEAD_ROLES


def _is_approver(user):
    """Check if user can approve (Head, DDG, DG, or Admin)."""
    role = (user.admin_role_id or "").upper()
    if role in APPROVER_ROLES:
        return True
    # Also check OfficerRole table
    return OfficerRole.objects.filter(
        officer=user.officer_id,
        role_type__in=list(APPROVER_ROLES),
    ).exists()


def _is_admin(user):
    """Check if user has admin-level role."""
    return (user.admin_role_id or "").upper() in SENIOR_ROLES


def _is_head(user):
    """Check if user has head role."""
    return (user.admin_role_id or "").upper() in (SENIOR_ROLES | HEAD_ROLES)


def _require_approver(request):
    """Return None if user is an approver, or a redirect response if not."""
    if not _is_approver(request.user):
        messages.error(request, "You do not have permission to approve.")
        return redirect("core:dashboard")
    return None


def _log_activity(user, action, entity_type, entity_id, remarks="", new_data=""):
    """Create an activity log entry."""
    ActivityLog.objects.create(
        actor_id=user.officer_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        new_data=new_data,
        remarks=remarks,
    )


def _get_office_filter(user):
    """Return a Q filter for office-level scoping, or None for global access."""
    role = (user.admin_role_id or "").upper()
    if role in SENIOR_ROLES:
        return Q()  # No filter -- see everything
    return Q(office=user.office)


def _check_auto_activate(assignment):
    """Check if all 5 sections approved; if so, auto-activate."""
    assignment.refresh_from_db()
    assignment.try_auto_activate()


# ============================================================
# Main Approvals Page
# ============================================================

@login_required
def approvals_page(request):
    """Display pending approvals page with all approval categories."""
    redir = _require_approver(request)
    if redir:
        return redir

    user = request.user
    office_q = _get_office_filter(user)

    # --- Workflow Approvals ---
    pending_registrations = (
        Assignment.objects
        .filter(office_q, registration_status="PENDING_APPROVAL")
        .select_related("registered_by", "office")
        .order_by("-created_at")
    )

    pending_tl_assignments = (
        Assignment.objects
        .filter(
            office_q,
            workflow_stage="TL_ASSIGNMENT",
        )
        .filter(Q(team_leader__isnull=True) | Q(team_leader__officer_id=""))
        .select_related("registered_by", "office")
        .order_by("-created_at")
    )

    # Legacy: DRAFT assignments needing approval
    pending_assignments = (
        Assignment.objects
        .filter(office_q, approval_status="DRAFT")
        .exclude(registration_status__in=["PENDING_APPROVAL", "APPROVED"])
        .select_related("team_leader", "office")
        .order_by("-created_at")
    )

    # Legacy: Unallocated assignments
    unallocated_assignments = (
        Assignment.objects
        .filter(
            office_q,
            approval_status__in=["APPROVED", "DRAFT"],
        )
        .filter(Q(team_leader__isnull=True) | Q(team_leader__officer_id=""))
        .exclude(workflow_stage__in=["REGISTRATION", "TL_ASSIGNMENT"])
        .select_related("team_leader", "office")
        .order_by("-created_at")
    )

    # --- Section Approvals ---
    pending_cost_estimations = (
        Assignment.objects
        .filter(office_q, cost_approval_status="SUBMITTED")
        .select_related("team_leader", "office")
        .order_by("-cost_submitted_at")
    )

    pending_team_constitutions = (
        Assignment.objects
        .filter(office_q, team_approval_status="SUBMITTED")
        .select_related("team_leader", "office")
        .annotate(team_count=Count("team_members"))
        .order_by("-team_submitted_at")
    )

    pending_milestone_plans = (
        Assignment.objects
        .filter(office_q, milestone_approval_status="SUBMITTED")
        .select_related("team_leader", "office")
        .annotate(milestone_count=Count("milestones"))
        .order_by("-milestone_submitted_at")
    )

    pending_revenue_shares = (
        Assignment.objects
        .filter(office_q, revenue_approval_status="SUBMITTED")
        .select_related("team_leader", "office")
        .annotate(share_count=Count("revenue_shares"))
        .order_by("-revenue_submitted_at")
    )

    # Legacy: pending revenue share change requests
    pending_revenue = (
        ApprovalRequest.objects
        .filter(
            request_type="REVENUE_SHARE_CHANGE",
            status="PENDING",
        )
        .select_related("requested_by")
        .order_by("-created_at")
    )
    if not (user.admin_role_id or "").upper() in SENIOR_ROLES:
        pending_revenue = pending_revenue.filter(office=user.office)

    # Pending milestones (old system)
    pending_milestones = (
        Milestone.objects
        .filter(approval_status="PENDING")
        .select_related("assignment", "assignment__office")
        .order_by("-updated_at")
    )
    if not (user.admin_role_id or "").upper() in SENIOR_ROLES:
        pending_milestones = pending_milestones.filter(
            assignment__office=user.office
        )

    # Pending invoice requests (for finance role visibility on approvals page)
    pending_invoices = (
        InvoiceRequest.objects
        .filter(status="PENDING")
        .select_related("assignment", "requested_by", "milestone")
        .order_by("-created_at")
    )
    if not (user.admin_role_id or "").upper() in SENIOR_ROLES:
        pending_invoices = pending_invoices.filter(
            assignment__office=user.office
        )

    # Pending tentative date changes
    pending_tentative_dates = (
        Milestone.objects
        .filter(tentative_date_status="PENDING")
        .select_related("assignment", "assignment__office")
        .order_by("-tentative_date_requested_at")
    )
    if not (user.admin_role_id or "").upper() in SENIOR_ROLES:
        pending_tentative_dates = pending_tentative_dates.filter(
            assignment__office=user.office
        )

    # Change requests: pending TL review
    pending_cr_tl_review = (
        ApprovalRequest.objects
        .filter(
            request_type="CHANGE_REQUEST",
            review_status="PENDING",
            status="PENDING",
        )
        .select_related("requested_by")
        .order_by("-created_at")
    )
    if not (user.admin_role_id or "").upper() in SENIOR_ROLES:
        pending_cr_tl_review = pending_cr_tl_review.filter(office=user.office)

    # Change requests: forwarded by TL, pending Head approval
    pending_cr_head_approval = (
        ApprovalRequest.objects
        .filter(
            request_type="CHANGE_REQUEST",
            review_status="FORWARDED",
            status="PENDING",
        )
        .select_related("requested_by")
        .order_by("-created_at")
    )
    if not (user.admin_role_id or "").upper() in SENIOR_ROLES:
        pending_cr_head_approval = pending_cr_head_approval.filter(
            office=user.office
        )

    # Officers grouped by office (for TL allocation dropdown)
    all_officers = (
        Officer.objects
        .filter(is_active=True)
        .order_by("office", "name")
    )
    office_officers = {}
    for officer in all_officers:
        oid = officer.office_id
        office_officers.setdefault(oid, []).append(officer)

    return render(request, "approvals/approvals.html", {
        "pending_registrations": pending_registrations,
        "pending_tl_assignments": pending_tl_assignments,
        "pending_assignments": pending_assignments,
        "unallocated_assignments": unallocated_assignments,
        "pending_cost_estimations": pending_cost_estimations,
        "pending_team_constitutions": pending_team_constitutions,
        "pending_milestone_plans": pending_milestone_plans,
        "pending_revenue_shares": pending_revenue_shares,
        "pending_revenue": pending_revenue,
        "pending_milestones": pending_milestones,
        "pending_team": [],
        "pending_invoices": pending_invoices,
        "pending_tentative_dates": pending_tentative_dates,
        "pending_cr_tl_review": pending_cr_tl_review,
        "pending_cr_head_approval": pending_cr_head_approval,
        "office_officers": office_officers,
    })


# ============================================================
# Registration Approval Workflow
# ============================================================

@login_required
@require_POST
def approve_registration(request, assignment_id):
    """Head approves a new activity registration."""
    redir = _require_approver(request)
    if redir:
        return redir

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment.approve_registration()
    assignment.save()

    # Update related approval_request
    ApprovalRequest.objects.filter(
        reference_id=assignment_id,
        request_type="REGISTRATION",
        status="PENDING",
    ).update(
        status="APPROVED",
        approved_by_id=request.user.officer_id,
        approved_at=timezone.now(),
    )

    _log_activity(
        request.user, "APPROVE", "registration", assignment_id,
        "Activity registration approved"
    )
    messages.success(request, "Registration approved successfully.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_registration(request, assignment_id):
    """Head rejects a new activity registration."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment.reject_registration()
    assignment.save()

    # Update related approval_request
    ApprovalRequest.objects.filter(
        reference_id=assignment_id,
        request_type="REGISTRATION",
        status="PENDING",
    ).update(
        status="REJECTED",
        approval_remarks=rejection_remarks,
        approved_by_id=request.user.officer_id,
        approved_at=timezone.now(),
    )

    _log_activity(
        request.user, "REJECT", "registration", assignment_id,
        rejection_remarks
    )
    messages.success(request, "Registration rejected.")
    return redirect("core:approvals")


# ============================================================
# Basic Info (Assignment) Approval
# ============================================================

@login_required
@require_POST
def approve_assignment(request, assignment_id):
    """Approve an assignment (basic info section)."""
    redir = _require_approver(request)
    if redir:
        return redir

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment.approval_status = "APPROVED"
    assignment.save()

    _check_auto_activate(assignment)

    _log_activity(
        request.user, "APPROVE", "assignment", assignment_id,
        "Assignment approved"
    )
    messages.success(request, "Assignment approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_assignment(request, assignment_id):
    """Reject an assignment."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment.approval_status = "REJECTED"
    assignment.save()

    _log_activity(
        request.user, "REJECT", "assignment", assignment_id,
        rejection_remarks
    )
    messages.success(request, "Assignment rejected.")
    return redirect("core:approvals")


# ============================================================
# Team Leader Allocation
# ============================================================

@login_required
@require_POST
def allocate_team_leader(request, assignment_id):
    """Allocate a team leader to an assignment."""
    redir = _require_approver(request)
    if redir:
        return redir

    team_leader_id = request.POST.get("team_leader_id", "")
    if not team_leader_id:
        messages.error(request, "Please select a team leader.")
        return redirect("core:approvals")

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    tl_officer = get_object_or_404(Officer, officer_id=team_leader_id)

    # Set TL and advance workflow
    assignment.team_leader = tl_officer
    if assignment.workflow_stage == "TL_ASSIGNMENT":
        assignment.assign_team_leader()
    else:
        assignment.workflow_stage = "DETAIL_ENTRY"
    assignment.save()

    # Add to assignment_team
    AssignmentTeam.objects.update_or_create(
        assignment=assignment,
        officer=tl_officer,
        defaults={
            "role": "TEAM_LEADER",
            "assigned_by": request.user.officer_id,
        },
    )

    # Set officer role if not already set
    if not tl_officer.admin_role_id:
        tl_officer.admin_role_id = "TEAM_LEADER"
        tl_officer.save(update_fields=["admin_role_id"])

    _log_activity(
        request.user, "UPDATE", "assignment", assignment_id,
        "Team leader allocated",
        new_data=f"team_leader={team_leader_id}",
    )
    messages.success(request, f"Team leader {tl_officer.name} allocated.")
    return redirect("core:approvals")


# ============================================================
# Generic Approval Request (Revenue Share Change, etc.)
# ============================================================

@login_required
@require_POST
def approve_request(request, request_id):
    """Approve a request (revenue share change, etc.)."""
    redir = _require_approver(request)
    if redir:
        return redir

    approval_req = get_object_or_404(ApprovalRequest, pk=request_id)
    approval_req.status = "APPROVED"
    approval_req.approved_by_id = request.user.officer_id
    approval_req.approved_at = timezone.now()
    approval_req.save()

    _log_activity(
        request.user, "APPROVE", "request", request_id,
        "Request approved"
    )
    messages.success(request, "Request approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_request(request, request_id):
    """Reject a request."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    approval_req = get_object_or_404(ApprovalRequest, pk=request_id)
    approval_req.status = "REJECTED"
    approval_req.approval_remarks = rejection_remarks
    approval_req.approved_by_id = request.user.officer_id
    approval_req.approved_at = timezone.now()
    approval_req.save()

    _log_activity(
        request.user, "REJECT", "request", request_id,
        rejection_remarks
    )
    messages.success(request, "Request rejected.")
    return redirect("core:approvals")


@login_required
@require_POST
def escalate_request(request, request_id):
    """Escalate a request to higher authority."""
    redir = _require_approver(request)
    if redir:
        return redir

    escalate_to = request.POST.get("escalate_to", "")
    approval_req = get_object_or_404(ApprovalRequest, pk=request_id)
    approval_req.status = "ESCALATED"
    approval_req.escalated_to = escalate_to
    approval_req.escalated_at = timezone.now()
    approval_req.save()

    _log_activity(
        request.user, "ESCALATE", "request", request_id,
        "Request escalated",
        new_data=f"escalated_to={escalate_to}",
    )
    messages.success(request, "Request escalated.")
    return redirect("core:approvals")


# ============================================================
# Cost Estimation Approval Workflow
# ============================================================

@login_required
@require_POST
def submit_cost_estimation(request, assignment_id):
    """TL submits cost estimation for Head approval."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Verify user is TL or head/admin
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_head(request.user):
            messages.error(request, "Only the team leader can submit cost estimation.")
            return redirect("core:dashboard")

    # Check expenditure items exist
    if not ExpenditureItem.objects.filter(assignment=assignment).exists():
        messages.error(request, "Please add expenditure items before submitting.")
        return redirect("core:dashboard")

    assignment._submit_section("cost", request.user.officer_id)
    assignment.save()

    _log_activity(
        request.user, "SUBMIT", "cost_estimation", assignment_id,
        "Cost estimation submitted for approval"
    )
    messages.success(request, "Cost estimation submitted for approval.")
    return redirect("core:approvals")


@login_required
@require_POST
def approve_cost_estimation(request, assignment_id):
    """Head approves cost estimation."""
    redir = _require_approver(request)
    if redir:
        return redir

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._approve_section("cost", request.user.officer_id)
    assignment.save()

    _check_auto_activate(assignment)

    _log_activity(
        request.user, "APPROVE", "cost_estimation", assignment_id,
        "Cost estimation approved"
    )
    messages.success(request, "Cost estimation approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_cost_estimation(request, assignment_id):
    """Head rejects cost estimation."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._reject_section("cost")
    assignment.save()

    _log_activity(
        request.user, "REJECT", "cost_estimation", assignment_id,
        rejection_remarks
    )
    messages.success(request, "Cost estimation rejected.")
    return redirect("core:approvals")


# ============================================================
# Team Constitution Approval Workflow
# ============================================================

@login_required
@require_POST
def submit_team_constitution(request, assignment_id):
    """TL submits team constitution for Head approval."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Verify user is TL or head/admin
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_head(request.user):
            messages.error(request, "Only the team leader can submit team constitution.")
            return redirect("core:dashboard")

    # Check team members exist
    if not AssignmentTeam.objects.filter(assignment=assignment).exists():
        messages.error(request, "Please add team members before submitting.")
        return redirect("core:dashboard")

    assignment._submit_section("team", request.user.officer_id)
    assignment.save()

    _log_activity(
        request.user, "SUBMIT", "team_constitution", assignment_id,
        "Team constitution submitted for approval"
    )
    messages.success(request, "Team constitution submitted for approval.")
    return redirect("core:approvals")


@login_required
@require_POST
def approve_team_constitution(request, assignment_id):
    """Head approves team constitution."""
    redir = _require_approver(request)
    if redir:
        return redir

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._approve_section("team", request.user.officer_id)
    assignment.save()

    _check_auto_activate(assignment)

    _log_activity(
        request.user, "APPROVE", "team_constitution", assignment_id,
        "Team constitution approved"
    )
    messages.success(request, "Team constitution approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_team_constitution(request, assignment_id):
    """Head rejects team constitution."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._reject_section("team")
    assignment.save()

    _log_activity(
        request.user, "REJECT", "team_constitution", assignment_id,
        rejection_remarks
    )
    messages.success(request, "Team constitution rejected.")
    return redirect("core:approvals")


# ============================================================
# Milestone Planning Approval Workflow
# ============================================================

@login_required
@require_POST
def submit_milestone_planning(request, assignment_id):
    """TL submits milestone planning for Head approval."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Verify user is TL or head/admin
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_head(request.user):
            messages.error(request, "Only the team leader can submit milestone planning.")
            return redirect("core:dashboard")

    # Check milestones exist
    if not Milestone.objects.filter(assignment=assignment).exists():
        messages.error(request, "Please add milestones before submitting.")
        return redirect("core:dashboard")

    assignment._submit_section("milestone", request.user.officer_id)
    assignment.save()

    _log_activity(
        request.user, "SUBMIT", "milestone_planning", assignment_id,
        "Milestone planning submitted for approval"
    )
    messages.success(request, "Milestone planning submitted for approval.")
    return redirect("core:approvals")


@login_required
@require_POST
def approve_milestone_planning(request, assignment_id):
    """Head approves milestone planning."""
    redir = _require_approver(request)
    if redir:
        return redir

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._approve_section("milestone", request.user.officer_id)
    assignment.save()

    # Also approve all pending milestones
    Milestone.objects.filter(
        assignment=assignment,
        approval_status="PENDING",
    ).update(
        approval_status="APPROVED",
        updated_at=timezone.now(),
    )

    _check_auto_activate(assignment)

    _log_activity(
        request.user, "APPROVE", "milestone_planning", assignment_id,
        "Milestone planning approved"
    )
    messages.success(request, "Milestone planning approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_milestone_planning(request, assignment_id):
    """Head rejects milestone planning."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._reject_section("milestone")
    assignment.save()

    _log_activity(
        request.user, "REJECT", "milestone_planning", assignment_id,
        rejection_remarks
    )
    messages.success(request, "Milestone planning rejected.")
    return redirect("core:approvals")


# ============================================================
# Revenue Share Approval Workflow
# ============================================================

@login_required
@require_POST
def submit_revenue_shares(request, assignment_id):
    """TL submits revenue shares for Head approval."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Verify user is TL or head/admin
    if assignment.team_leader and assignment.team_leader.officer_id != request.user.officer_id:
        if not _is_head(request.user):
            messages.error(request, "Only the team leader can submit revenue shares.")
            return redirect("core:dashboard")

    # Check revenue shares exist
    shares = RevenueShare.objects.filter(assignment=assignment)
    if not shares.exists():
        messages.error(request, "Please add revenue shares before submitting.")
        return redirect("core:dashboard")

    # Verify total is 100%
    from django.db.models import Sum
    total = shares.aggregate(total=Sum("share_percent"))["total"] or 0
    if abs(total - 100) > 0.01:
        messages.error(request, "Revenue shares must total 100%.")
        return redirect("core:dashboard")

    assignment._submit_section("revenue", request.user.officer_id)
    assignment.save()

    _log_activity(
        request.user, "SUBMIT", "revenue_shares", assignment_id,
        "Revenue shares submitted for approval"
    )
    messages.success(request, "Revenue shares submitted for approval.")
    return redirect("core:approvals")


@login_required
@require_POST
def approve_revenue_shares(request, assignment_id):
    """Head approves revenue shares."""
    redir = _require_approver(request)
    if redir:
        return redir

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._approve_section("revenue", request.user.officer_id)
    assignment.save()

    _check_auto_activate(assignment)

    _log_activity(
        request.user, "APPROVE", "revenue_shares", assignment_id,
        "Revenue shares approved"
    )
    messages.success(request, "Revenue shares approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_revenue_shares(request, assignment_id):
    """Head rejects revenue shares."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    assignment._reject_section("revenue")
    assignment.save()

    _log_activity(
        request.user, "REJECT", "revenue_shares", assignment_id,
        rejection_remarks
    )
    messages.success(request, "Revenue shares rejected.")
    return redirect("core:approvals")


# ============================================================
# Tentative Date Change Approval
# ============================================================

@login_required
@require_POST
def approve_tentative_date(request, milestone_id):
    """Head approves tentative date change request."""
    redir = _require_approver(request)
    if redir:
        return redir

    milestone = get_object_or_404(Milestone, pk=milestone_id)
    milestone.tentative_date_status = "APPROVED"
    milestone.tentative_date_approved_by = request.user.officer_id
    milestone.tentative_date_approved_at = timezone.now()
    milestone.save()

    _log_activity(
        request.user, "APPROVE", "tentative_date", milestone.assignment_id,
        "Tentative date change approved"
    )
    messages.success(request, "Tentative date change approved.")
    return redirect("core:approvals")


@login_required
@require_POST
def reject_tentative_date(request, milestone_id):
    """Head rejects tentative date change request."""
    redir = _require_approver(request)
    if redir:
        return redir

    rejection_remarks = request.POST.get("rejection_remarks", "")
    milestone = get_object_or_404(Milestone, pk=milestone_id)

    # Revert tentative date to target date
    milestone.tentative_date = milestone.target_date
    milestone.tentative_date_status = "REJECTED"
    milestone.tentative_date_approved_by = request.user.officer_id
    milestone.tentative_date_approved_at = timezone.now()
    milestone.save()

    _log_activity(
        request.user, "REJECT", "tentative_date", milestone.assignment_id,
        rejection_remarks or "Tentative date change rejected"
    )
    messages.success(request, "Tentative date change rejected.")
    return redirect("core:approvals")
