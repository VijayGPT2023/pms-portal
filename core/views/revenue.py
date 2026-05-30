"""
Revenue sharing views: fill and update revenue shares per assignment.
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import (
    ActivityLog, Assignment, Officer, RevenueAllocationFlag, RevenueShare,
)


def _is_head(user):
    return (user.admin_role_id or "") in (
        "ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD",
    )


@login_required
def revenue_share_page(request, assignment_id):
    """Display revenue share form."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    officers = Officer.objects.filter(is_active=True).order_by("name")
    shares = (
        RevenueShare.objects.filter(assignment=assignment)
        .select_related("officer")
        .order_by("-share_percent")
    )
    existing_shares_json = json.dumps([
        {
            "officer_id": s.officer.officer_id,
            "share_percent": s.share_percent,
            "share_amount": s.share_amount,
        }
        for s in shares
    ])
    total_share = sum(s.share_percent or 0 for s in shares)

    # Flags (SCOPE_V2 §3.7)
    flags = list(
        RevenueAllocationFlag.objects.filter(assignment=assignment)
        .select_related("raised_by", "revenue_share")
        .order_by("-created_at")
    )
    open_flag_share_ids = {f.revenue_share_id for f in flags if f.status == "OPEN" and f.revenue_share_id}

    return render(request, "revenue/revenue_share_form.html", {
        "assignment": assignment,
        "officers": officers,
        "shares": shares,
        "existing_shares": shares,
        "existing_shares_json": existing_shares_json,
        "total_share": total_share,
        "flags": flags,
        "open_flag_share_ids": open_flag_share_ids,
        "is_head": _is_head(request.user),
        "is_tl": assignment.team_leader_id == request.user.officer_id,
        "current_officer_id": request.user.officer_id,
    })


@login_required
def revenue_share_submit(request, assignment_id):
    """Handle revenue share form submission."""
    if request.method != "POST":
        return redirect("core:revenue_share_page", assignment_id=assignment_id)

    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Extract shares from form
    shares = []
    i = 0
    while f"officer_id_{i}" in request.POST:
        officer_id = request.POST.get(f"officer_id_{i}")
        share_percent_str = request.POST.get(f"share_percent_{i}", "0")
        if officer_id and share_percent_str:
            try:
                share_percent = float(share_percent_str)
                if share_percent > 0:
                    total_revenue = assignment.total_revenue or assignment.gross_value or 0
                    share_amount = (share_percent * total_revenue) / 100
                    shares.append({
                        "officer_id": officer_id,
                        "share_percent": share_percent,
                        "share_amount": share_amount,
                    })
            except ValueError:
                pass
        i += 1

    # Validate total percentage
    total_percent = sum(s["share_percent"] for s in shares)
    if abs(total_percent - 100) > 0.01 and total_percent > 0:
        officers = Officer.objects.filter(is_active=True).order_by("name")
        existing_shares = (
            RevenueShare.objects.filter(assignment=assignment)
            .select_related("officer")
            .order_by("-share_percent")
        )
        return render(request, "revenue/revenue_share_form.html", {
            "assignment": assignment,
            "officers": officers,
            "existing_shares": existing_shares,
            "existing_shares_json": json.dumps([]),
            "error": f"Total percentage must be 100%. Current total: {total_percent:.2f}%",
        }, status=400)

    # Delete existing and insert new
    RevenueShare.objects.filter(assignment=assignment).delete()
    for share in shares:
        officer = Officer.objects.get(officer_id=share["officer_id"])
        RevenueShare.objects.create(
            assignment=assignment,
            officer=officer,
            share_percent=share["share_percent"],
            share_amount=share["share_amount"],
        )

    # Reset approval statuses if previously approved
    save_fields = []
    if assignment.revenue_approval_status == "APPROVED":
        assignment.revenue_approval_status = "SUBMITTED"
        save_fields.append("revenue_approval_status")
    if assignment.team_approval_status == "APPROVED":
        assignment.team_approval_status = "SUBMITTED"
        save_fields.append("team_approval_status")
    if save_fields:
        assignment.save(update_fields=save_fields)

    next_step = request.POST.get("next_step", "")
    if next_step == "finish":
        return redirect(f"/assignment/view/{assignment_id}?completed=1")

    return redirect(f"/assignment/view/{assignment_id}")


# ============================================================
# Revenue Allocation Flags (SCOPE_V2 §3.7)
# ============================================================

@login_required
@require_POST
def raise_flag(request, assignment_id):
    """Affected officer flags their revenue share. Reason mandatory."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "A reason is required to raise a flag.")
        return redirect("core:revenue_share_page", assignment_id=assignment_id)

    share_id = request.POST.get("revenue_share_id") or None
    share = None
    if share_id:
        share = RevenueShare.objects.filter(pk=share_id, assignment=assignment).first()

    # Only the affected officer may flag their own row.
    if share and share.officer_id != request.user.officer_id:
        messages.error(request, "You can only flag your own revenue share.")
        return redirect("core:revenue_share_page", assignment_id=assignment_id)

    existing = RevenueAllocationFlag.objects.filter(
        assignment=assignment, raised_by=request.user,
        revenue_share=share, status="OPEN",
    ).exists()
    if existing:
        messages.warning(request, "You already have an open flag on this row.")
        return redirect("core:revenue_share_page", assignment_id=assignment_id)

    flag = RevenueAllocationFlag.objects.create(
        assignment=assignment, revenue_share=share,
        raised_by=request.user, reason=reason,
    )
    ActivityLog.objects.create(
        actor_id=request.user.officer_id, action="CREATE",
        entity_type="revenue_flag", entity_id=flag.pk,
        remarks=f"Flag raised on revenue allocation of {assignment.assignment_no}",
    )
    messages.success(request, "Flag raised. The Team Leader and Head can now see it.")
    return redirect("core:revenue_share_page", assignment_id=assignment_id)


@login_required
@require_POST
def address_flag(request, flag_id):
    """TL or Head marks a flag as addressed with a note."""
    flag = get_object_or_404(RevenueAllocationFlag.objects.select_related("assignment"), pk=flag_id)
    is_tl = flag.assignment.team_leader_id == request.user.officer_id
    if not (is_tl or _is_head(request.user)):
        messages.error(request, "Only the Team Leader or a Head can address a flag.")
        return redirect("core:revenue_share_page", assignment_id=flag.assignment_id)
    if flag.status != "OPEN":
        messages.error(request, f"Flag is already {flag.get_status_display()}.")
        return redirect("core:revenue_share_page", assignment_id=flag.assignment_id)

    flag.status = "ADDRESSED"
    flag.resolution_note = (request.POST.get("resolution_note") or "").strip()
    flag.addressed_by = request.user
    flag.addressed_at = timezone.now()
    flag.save(update_fields=["status", "resolution_note", "addressed_by", "addressed_at", "updated_at"])

    ActivityLog.objects.create(
        actor_id=request.user.officer_id, action="UPDATE",
        entity_type="revenue_flag", entity_id=flag.pk,
        remarks=f"Flag addressed on {flag.assignment.assignment_no}",
    )
    messages.success(request, "Flag marked as addressed.")
    return redirect("core:revenue_share_page", assignment_id=flag.assignment_id)


@login_required
@require_POST
def withdraw_flag(request, flag_id):
    """The flagger withdraws their own flag."""
    flag = get_object_or_404(RevenueAllocationFlag, pk=flag_id)
    if flag.raised_by_id != request.user.officer_id:
        messages.error(request, "Only the officer who raised the flag can withdraw it.")
        return redirect("core:revenue_share_page", assignment_id=flag.assignment_id)
    if flag.status != "OPEN":
        messages.error(request, f"Flag is already {flag.get_status_display()}.")
        return redirect("core:revenue_share_page", assignment_id=flag.assignment_id)

    flag.status = "WITHDRAWN"
    flag.save(update_fields=["status", "updated_at"])
    ActivityLog.objects.create(
        actor_id=request.user.officer_id, action="UPDATE",
        entity_type="revenue_flag", entity_id=flag.pk,
        remarks="Flag withdrawn by flagger",
    )
    messages.success(request, "Flag withdrawn.")
    return redirect("core:revenue_share_page", assignment_id=flag.assignment_id)


@login_required
def api_get_officers(request):
    """API endpoint to get officers list."""
    officers = list(
        Officer.objects.filter(is_active=True)
        .values("officer_id", "name", "office_id", "designation")
        .order_by("name")
    )
    return JsonResponse({"officers": officers})


@login_required
def api_get_assignment(request, assignment_id):
    """API endpoint to get assignment details."""
    try:
        assignment = Assignment.objects.get(pk=assignment_id)
    except Assignment.DoesNotExist:
        return JsonResponse({"error": "Assignment not found"}, status=404)
    return JsonResponse({
        "assignment": {
            "id": assignment.pk,
            "assignment_no": assignment.assignment_no,
            "title": assignment.title,
            "total_revenue": assignment.total_revenue,
            "gross_value": assignment.gross_value,
        }
    })
