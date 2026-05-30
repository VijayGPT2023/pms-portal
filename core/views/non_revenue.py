"""
Non-Revenue Activity Management views.
Workflow: Suggestion -> Approval -> In Progress -> Completed
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import NonRevenueSuggestion, Office, Officer, OfficerRole


ACTIVITY_TYPES = [
    {"value": "CAPACITY_BUILDING", "label": "Capacity Building"},
    {"value": "KNOWLEDGE_SHARING", "label": "Knowledge Sharing"},
    {"value": "INTERNAL_PROJECT", "label": "Internal Project"},
    {"value": "RESEARCH", "label": "Research & Development"},
    {"value": "DOCUMENTATION", "label": "Documentation"},
    {"value": "PROCESS_IMPROVEMENT", "label": "Process Improvement"},
    {"value": "OTHER", "label": "Other"},
]

ACTIVITY_TYPE_LABELS = {a["value"]: a["label"] for a in ACTIVITY_TYPES}


def _is_office_head(user):
    """Check if user holds a head-level role."""
    if user.admin_role_id in ("ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD"):
        return True
    return OfficerRole.objects.filter(
        officer=user,
        role_type__in=["DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD"],
        effective_to__isnull=True,
    ).exists()


@login_required
def list_suggestions(request):
    """List all non-revenue suggestions with filters."""
    status_filter = request.GET.get("status")
    office_filter = request.GET.get("office")
    view = request.GET.get("view")

    qs = NonRevenueSuggestion.objects.select_related("officer", "office", "created_by", "approved_by")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if office_filter:
        qs = qs.filter(office__office_id=office_filter)

    admin_role = user_admin_role(request.user)
    if view == "pending_approval" and admin_role in ("ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD"):
        qs = qs.filter(approval_status="PENDING")
    elif view == "my_created":
        qs = qs.filter(created_by=request.user)
    elif view == "my_allocated":
        qs = qs.filter(officer=request.user)
    elif admin_role not in ("ADMIN", "DG", "DDG-I", "DDG-II"):
        qs = qs.filter(office=request.user.office)

    qs = qs.order_by("-created_at")

    offices = Office.objects.order_by("office_name")
    status_counts = dict(
        NonRevenueSuggestion.objects.values_list("status").annotate(c=Count("id")).values_list("status", "c")
    )
    pending_count = NonRevenueSuggestion.objects.filter(approval_status="PENDING").count()

    return render(request, "non_revenue/list.html", {
        "suggestions": qs,
        "offices": offices,
        "status_counts": status_counts,
        "pending_approval_count": pending_count,
        "filter_status": status_filter,
        "filter_office": office_filter,
        "filter_view": view,
        "is_head": _is_office_head(request.user),
    })


@login_required
def create_suggestion_form(request):
    """Show form to create new non-revenue suggestion."""
    offices = Office.objects.order_by("office_name")
    return render(request, "non_revenue/form.html", {
        "offices": offices,
        "activity_types": ACTIVITY_TYPES,
        "suggestion": None,
        "is_new": True,
    })


@login_required
def create_suggestion(request):
    """Create new non-revenue suggestion."""
    if request.method != "POST":
        return redirect("core:non_revenue_list")

    office = Office.objects.get(office_id=request.POST["office_id"])

    # Generate suggestion number
    from django.utils.timezone import now
    today = now().date()
    prefix = f"NR-{office.office_id}-{today.strftime('%Y%m')}"
    count = NonRevenueSuggestion.objects.filter(suggestion_number__startswith=prefix).count()
    suggestion_number = f"{prefix}-{count + 1:03d}"

    NonRevenueSuggestion.objects.create(
        suggestion_number=suggestion_number,
        title=request.POST["title"],
        description=request.POST.get("description", ""),
        activity_type=request.POST["activity_type"],
        beneficiary=request.POST.get("beneficiary", ""),
        office=office,
        justification=request.POST.get("justification", ""),
        expected_outcome=request.POST.get("expected_outcome", ""),
        notional_value=float(request.POST.get("notional_value", 0) or 0),
        man_days=float(request.POST.get("man_days", 0) or 0),
        target_start_date=request.POST.get("target_start_date") or None,
        target_end_date=request.POST.get("target_end_date") or None,
        status="PENDING_APPROVAL",
        approval_status="PENDING",
        remarks=request.POST.get("remarks", ""),
        created_by=request.user,
    )
    return redirect("/non-revenue/?view=my_created")


@login_required
def view_suggestion(request, suggestion_id):
    """View non-revenue suggestion details."""
    suggestion = get_object_or_404(
        NonRevenueSuggestion.objects.select_related("officer", "office", "created_by", "approved_by"),
        pk=suggestion_id,
    )
    officers = Officer.objects.filter(
        Q(office=suggestion.office) | Q(admin_role_id__in=["ADMIN", "DG", "DDG-I", "DDG-II"])
    ).order_by("name")

    is_head = _is_office_head(request.user)
    can_edit = (
        (suggestion.created_by == request.user and suggestion.approval_status == "PENDING")
        or is_head
    )

    return render(request, "non_revenue/view.html", {
        "suggestion": suggestion,
        "officers": officers,
        "is_head": is_head,
        "can_edit": can_edit,
        "activity_types": ACTIVITY_TYPE_LABELS,
    })


@login_required
def approve_suggestion(request, suggestion_id):
    """Approve non-revenue suggestion."""
    if request.method != "POST":
        return redirect("core:non_revenue_view", suggestion_id=suggestion_id)

    suggestion = get_object_or_404(NonRevenueSuggestion, pk=suggestion_id)
    if not _is_office_head(request.user):
        raise Http404("Not authorized")

    officer_id = request.POST.get("officer_id")
    suggestion.approval_status = "APPROVED"
    suggestion.status = "IN_PROGRESS"
    suggestion.approved_by = request.user
    suggestion.approved_at = timezone.now()
    if officer_id:
        try:
            suggestion.officer = Officer.objects.get(officer_id=officer_id)
        except Officer.DoesNotExist:
            pass
    suggestion.save()
    return redirect("core:non_revenue_view", suggestion_id=suggestion_id)


@login_required
def reject_suggestion(request, suggestion_id):
    """Reject non-revenue suggestion."""
    if request.method != "POST":
        return redirect("core:non_revenue_view", suggestion_id=suggestion_id)

    suggestion = get_object_or_404(NonRevenueSuggestion, pk=suggestion_id)
    if not _is_office_head(request.user):
        raise Http404("Not authorized")

    suggestion.approval_status = "REJECTED"
    suggestion.status = "REJECTED"
    suggestion.rejection_reason = request.POST.get("rejection_reason", "")
    suggestion.approved_by = request.user
    suggestion.approved_at = timezone.now()
    suggestion.save()
    return redirect("/non-revenue/?view=pending_approval")


@login_required
def update_suggestion_progress(request, suggestion_id):
    """Update progress on non-revenue suggestion."""
    if request.method != "POST":
        return redirect("core:non_revenue_view", suggestion_id=suggestion_id)

    suggestion = get_object_or_404(NonRevenueSuggestion, pk=suggestion_id)
    if suggestion.officer != request.user and not _is_office_head(request.user):
        raise Http404("Not authorized")

    suggestion.current_update = request.POST.get("current_update", "")
    man_days = request.POST.get("man_days")
    if man_days not in (None, ""):
        suggestion.man_days = float(man_days or 0)
    status = request.POST.get("status")
    if status:
        suggestion.status = status
    suggestion.save()
    return redirect("core:non_revenue_view", suggestion_id=suggestion_id)


@login_required
def complete_suggestion(request, suggestion_id):
    """Mark non-revenue suggestion as completed."""
    if request.method != "POST":
        return redirect("core:non_revenue_view", suggestion_id=suggestion_id)

    suggestion = get_object_or_404(NonRevenueSuggestion, pk=suggestion_id)
    if suggestion.officer != request.user and not _is_office_head(request.user):
        raise Http404("Not authorized")

    suggestion.status = "COMPLETED"
    suggestion.save()
    return redirect("core:non_revenue_view", suggestion_id=suggestion_id)


def user_admin_role(user):
    """Get user's admin_role_id safely."""
    return getattr(user, "admin_role_id", "") or ""
