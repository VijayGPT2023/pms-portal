"""
Revenue sharing views: fill and update revenue shares per assignment.
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Assignment, Officer, RevenueShare


@login_required
def revenue_share_page(request, assignment_id):
    """Display revenue share form."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    officers = Officer.objects.filter(is_active=True).order_by("name")
    existing_shares = (
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
        for s in existing_shares
    ])
    return render(request, "revenue/revenue_share_form.html", {
        "assignment": assignment,
        "officers": officers,
        "existing_shares": existing_shares,
        "existing_shares_json": existing_shares_json,
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
