"""
Utilization Claims views.
Workflow: Officer fills -> Submits -> TL Approves -> Head Rectifies -> FINAL
"""
import calendar
from datetime import date, datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum, Case, When, F, Value
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import (
    Assignment, AssignmentTeam, Officer, OfficerRole, Office,
    UtilizationClaim,
)

CLAIM_TYPE_LABELS = {ct[0]: ct[1] for ct in settings.UTILIZATION_CLAIM_TYPES}
STATUS_LABELS = {
    "DRAFT": "Draft", "SUBMITTED": "Submitted", "TL_APPROVED": "TL Approved",
    "HEAD_RECTIFIED": "Head Rectified", "FINAL": "Final",
}


def _is_tl_for_officer(user, officer):
    """Check if user is TL for assignments where officer is a member."""
    return Assignment.objects.filter(
        team_leader=user,
        team_members__officer=officer,
        team_members__is_active=True,
    ).exists()


def _is_head_for_officer(user, officer):
    """Check if user is office head for the officer."""
    role = user.admin_role_id or ""
    if role in ("ADMIN", "DG", "DDG-I", "DDG-II"):
        return True
    if role in ("RD_HEAD", "GROUP_HEAD"):
        return officer.office_id == user.office_id
    return False


def _get_working_days(year, month):
    """Calculate working days (weekdays) in a month."""
    num_days = calendar.monthrange(year, month)[1]
    return sum(1 for d in range(1, num_days + 1) if date(year, month, d).weekday() < 5)


@login_required
def utilization_list(request):
    """List my claims."""
    month = request.GET.get("month")
    status = request.GET.get("status")

    qs = UtilizationClaim.objects.filter(officer=request.user).select_related("assignment")
    if month:
        qs = qs.filter(claim_month=month)
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("-activity_date")

    return render(request, "utilization/list.html", {
        "claims": qs,
        "filter_month": month,
        "filter_status": status,
        "claim_type_labels": CLAIM_TYPE_LABELS,
        "status_labels": STATUS_LABELS,
    })


@login_required
def new_claim_form(request):
    """New claim form."""
    assignments = Assignment.objects.filter(
        Q(team_leader=request.user)
        | Q(team_members__officer=request.user, team_members__is_active=True)
        | Q(registered_by=request.user),
        status__in=["Not Started", "Ongoing", "In Progress"],
    ).distinct().order_by("title")

    return render(request, "utilization/form.html", {
        "claim": None,
        "assignments": assignments,
        "claim_types": settings.UTILIZATION_CLAIM_TYPES,
        "is_edit": False,
    })


@login_required
def create_claim(request):
    """Create new claim."""
    if request.method != "POST":
        return redirect("core:utilization_list")

    claim_type = request.POST.get("claim_type", "")
    activity_date_str = request.POST.get("activity_date", "")
    man_days = float(request.POST.get("man_days_claimed", 0))
    assignment_id = request.POST.get("assignment_id") or None

    try:
        act_date = datetime.strptime(activity_date_str, "%Y-%m-%d").date()
        claim_month = act_date.strftime("%Y-%m")
    except ValueError:
        return redirect("core:new_claim_form")

    # Generate claim number
    prefix = f"UC-{request.user.officer_id}-{claim_month}"
    count = UtilizationClaim.objects.filter(claim_number__startswith=prefix).count()
    claim_number = f"{prefix}-{count + 1:03d}"

    assignment = None
    if assignment_id:
        try:
            assignment = Assignment.objects.get(pk=int(assignment_id))
        except (Assignment.DoesNotExist, ValueError):
            pass

    UtilizationClaim.objects.create(
        claim_number=claim_number,
        officer=request.user,
        assignment=assignment,
        claim_month=claim_month,
        activity_date=act_date,
        man_days_claimed=man_days,
        activity_description=request.POST.get("activity_description", "").strip(),
        claim_type=claim_type,
        status="DRAFT",
    )
    return redirect("core:utilization_list")


@login_required
def edit_claim_form(request, claim_id):
    """Edit claim form."""
    claim = get_object_or_404(UtilizationClaim, pk=claim_id, officer=request.user)
    if claim.status != "DRAFT":
        raise Http404("Only DRAFT claims can be edited")

    assignments = Assignment.objects.filter(
        Q(team_leader=request.user)
        | Q(team_members__officer=request.user, team_members__is_active=True)
        | Q(registered_by=request.user),
        status__in=["Not Started", "Ongoing", "In Progress"],
    ).distinct().order_by("title")

    return render(request, "utilization/form.html", {
        "claim": claim,
        "assignments": assignments,
        "claim_types": settings.UTILIZATION_CLAIM_TYPES,
        "is_edit": True,
    })


@login_required
def update_claim(request, claim_id):
    """Update claim."""
    if request.method != "POST":
        return redirect("core:utilization_list")

    claim = get_object_or_404(UtilizationClaim, pk=claim_id, officer=request.user)
    if claim.status != "DRAFT":
        raise Http404("Only DRAFT claims can be edited")

    activity_date_str = request.POST.get("activity_date", "")
    try:
        act_date = datetime.strptime(activity_date_str, "%Y-%m-%d").date()
        claim_month = act_date.strftime("%Y-%m")
    except ValueError:
        return redirect("core:utilization_list")

    assignment_id = request.POST.get("assignment_id") or None
    assignment = None
    if assignment_id:
        try:
            assignment = Assignment.objects.get(pk=int(assignment_id))
        except (Assignment.DoesNotExist, ValueError):
            pass

    claim.assignment = assignment
    claim.activity_date = act_date
    claim.claim_month = claim_month
    claim.claim_type = request.POST.get("claim_type", claim.claim_type)
    claim.man_days_claimed = float(request.POST.get("man_days_claimed", 0))
    claim.activity_description = request.POST.get("activity_description", "").strip()
    claim.save()
    return redirect("core:utilization_list")


@login_required
def submit_claim(request, claim_id):
    """Submit claim (DRAFT -> SUBMITTED)."""
    if request.method != "POST":
        return redirect("core:utilization_list")

    claim = get_object_or_404(UtilizationClaim, pk=claim_id, officer=request.user)
    if claim.status != "DRAFT":
        raise Http404("Only DRAFT claims can be submitted")

    claim.status = "SUBMITTED"
    claim.submitted_at = timezone.now()
    claim.save()
    return redirect("core:utilization_list")


@login_required
def pending_approval(request):
    """TL: Pending approval list."""
    claims = UtilizationClaim.objects.filter(
        status="SUBMITTED",
    ).filter(
        Q(officer__team_memberships__assignment__team_leader=request.user,
          officer__team_memberships__is_active=True)
        | Q(officer__office=request.user.office)
    ).select_related("officer", "assignment").distinct().order_by("-submitted_at")

    return render(request, "utilization/pending.html", {
        "claims": claims,
        "claim_type_labels": CLAIM_TYPE_LABELS,
    })


@login_required
def tl_approve(request, claim_id):
    """TL approves claim (SUBMITTED -> TL_APPROVED)."""
    if request.method != "POST":
        return redirect("core:utilization_pending")

    claim = get_object_or_404(UtilizationClaim, pk=claim_id, status="SUBMITTED")
    claim.status = "TL_APPROVED"
    claim.tl_approved_by = request.user
    claim.tl_approved_at = timezone.now()
    claim.tl_remarks = request.POST.get("remarks", "").strip()
    claim.save()
    return redirect("core:utilization_pending")


@login_required
def tl_reject(request, claim_id):
    """TL rejects claim (SUBMITTED -> DRAFT)."""
    if request.method != "POST":
        return redirect("core:utilization_pending")

    claim = get_object_or_404(UtilizationClaim, pk=claim_id, status="SUBMITTED")
    claim.status = "DRAFT"
    claim.tl_remarks = request.POST.get("remarks", "").strip()
    claim.save()
    return redirect("core:utilization_pending")


@login_required
def pending_rectification(request):
    """Head: Pending rectification list."""
    role = request.user.admin_role_id or ""
    if role in ("ADMIN", "DG", "DDG-I", "DDG-II"):
        claims = UtilizationClaim.objects.filter(status="TL_APPROVED")
    elif role in ("RD_HEAD", "GROUP_HEAD"):
        claims = UtilizationClaim.objects.filter(
            status="TL_APPROVED", officer__office=request.user.office
        )
    else:
        return redirect("core:utilization_list")

    claims = claims.select_related("officer", "assignment").order_by("-tl_approved_at")

    return render(request, "utilization/rectification.html", {
        "claims": claims,
        "claim_type_labels": CLAIM_TYPE_LABELS,
    })


@login_required
def head_rectify(request, claim_id):
    """Head rectifies claim (TL_APPROVED -> HEAD_RECTIFIED)."""
    if request.method != "POST":
        return redirect("core:utilization_rectification")

    claim = get_object_or_404(UtilizationClaim, pk=claim_id, status="TL_APPROVED")
    if not _is_head_for_officer(request.user, claim.officer):
        raise Http404("Not authorized")

    claim.status = "HEAD_RECTIFIED"
    claim.rectified_days = float(request.POST.get("rectified_days", claim.man_days_claimed))
    claim.head_rectified_by = request.user
    claim.head_rectified_at = timezone.now()
    claim.head_remarks = request.POST.get("remarks", "").strip()
    claim.save()
    return redirect("core:utilization_rectification")


@login_required
def finalize_claim(request, claim_id):
    """Head finalizes claim (HEAD_RECTIFIED -> FINAL)."""
    if request.method != "POST":
        return redirect("core:utilization_rectification")

    claim = get_object_or_404(UtilizationClaim, pk=claim_id, status="HEAD_RECTIFIED")
    if not _is_head_for_officer(request.user, claim.officer):
        raise Http404("Not authorized")

    claim.status = "FINAL"
    claim.save()
    return redirect("core:utilization_rectification")


@login_required
def utilization_summary(request):
    """Utilization summary MIS."""
    month = request.GET.get("month") or date.today().strftime("%Y-%m")
    office_filter = request.GET.get("office")

    qs = Officer.objects.filter(is_active=True)

    role = request.user.admin_role_id or ""
    if office_filter and role in ("ADMIN", "DG", "DDG-I", "DDG-II"):
        qs = qs.filter(office__office_id=office_filter)
    elif role in ("RD_HEAD", "GROUP_HEAD"):
        qs = qs.filter(office=request.user.office)

    summary = qs.annotate(
        total_claimed=Sum(
            "utilization_claims__man_days_claimed",
            filter=Q(utilization_claims__claim_month=month),
        ),
        total_approved=Sum(
            "utilization_claims__man_days_claimed",
            filter=Q(
                utilization_claims__claim_month=month,
                utilization_claims__status__in=["TL_APPROVED", "HEAD_RECTIFIED", "FINAL"],
            ),
        ),
        claim_count=Count(
            "utilization_claims",
            filter=Q(utilization_claims__claim_month=month),
        ),
    ).filter(claim_count__gt=0).order_by("name")

    offices = Office.objects.order_by("office_name")

    try:
        year, mon = int(month.split("-")[0]), int(month.split("-")[1])
        working_days = _get_working_days(year, mon)
    except (ValueError, IndexError):
        working_days = 22

    return render(request, "utilization/summary.html", {
        "summary": summary,
        "filter_month": month,
        "filter_office": office_filter,
        "offices": offices,
        "working_days": working_days,
    })
