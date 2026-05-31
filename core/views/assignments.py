"""
Assignment views: list, create, view, edit, milestones, expenditure.
Ported from FastAPI assignment_routes.py to Django views.
"""
import re
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Count, Q, F, Case, When, Value, FloatField
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from core.models import (
    Assignment,
    Milestone,
    ExpenditureHead,
    ExpenditureItem,
    ExpenditureEntry,
    Office,
    Officer,
    RevenueShare,
    ConfigOption,
    ApprovalRequest,
    ActivityLog,
    InvoiceRequest,
    PaymentReceipt,
    SiteConfig,
)

# ---------------------------------------------------------------------------
# Constants (mirrored from app/config.py)
# ---------------------------------------------------------------------------

ASSIGNMENT_STATUS_OPTIONS = [
    "Not Started", "Ongoing", "Completed", "On Hold", "Cancelled",
]

CLIENT_TYPE_OPTIONS = [
    "Central Government", "State Government", "PSU", "Private",
    "International", "Others",
]

DOMAIN_OPTIONS = [
    "ES", "IE", "HRM", "IT", "Agri", "TM", "General",
]

ACTIVITY_TYPE_CODES = {
    "ASSIGNMENT": "ASG",
    "TRAINING": "TRG",
    "DEVELOPMENT": "DEV",
}

DEV_WORK_QUANTIFICATION = {
    "PROPOSAL_PREP": {
        "slabs": [
            (20, 1), (50, 2), (100, 3), (200, 4), (float("inf"), 5),
        ]
    },
    "EVENT_MGMT": {"max_days": 5},
    "COMMITTEE": {"per_member_days": 0.25},
    "MEETING": {"min_days": 0.5},
}

TRAINING_MODE = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config_options(category: str):
    """Return config options from DB, with hardcoded fallback."""
    options = list(
        ConfigOption.objects.filter(category=category, is_active=True)
        .order_by("sort_order")
        .values("option_value", "option_label")
    )
    if not options:
        if category == "domain":
            return [{"option_value": d, "option_label": d} for d in DOMAIN_OPTIONS]
        elif category == "client_type":
            return [{"option_value": c, "option_label": c} for c in CLIENT_TYPE_OPTIONS]
        elif category == "status":
            return [{"option_value": s, "option_label": s} for s in ASSIGNMENT_STATUS_OPTIONS]
    return options


def _get_current_fy():
    """Return current financial year string like '2025-26'."""
    today = date.today()
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    else:
        return f"{today.year - 1}-{str(today.year)[2:]}"


def _get_fy_for_date(d):
    """Return FY string for a given date."""
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    else:
        return f"{d.year - 1}-{str(d.year)[2:]}"


def _generate_assignment_number(office_id, assignment_type, client_name):
    """Generate assignment number: NPC/OFFICE/TYPE/CLIENT/SEQ/FY."""
    type_code = ACTIVITY_TYPE_CODES.get(assignment_type, "ASG")

    if client_name:
        clean = re.sub(r"[^A-Za-z0-9]", "", client_name)
        client_code = clean[:3].upper() if clean else "GEN"
    else:
        client_code = "GEN"

    fy = _get_current_fy()
    next_no = (
        Assignment.objects.filter(
            office=office_id,
            assignment_no__startswith=f"NPC/{office_id}/",
            assignment_no__endswith=f"/{fy}",
        ).count()
        + 1
    )
    return f"NPC/{office_id}/{type_code}/{client_code}/{next_no:04d}/{fy}"


def _calculate_dev_man_days(sub_type, proposal_value=0, num_members=0, event_days=0):
    """Auto-calculate man_days based on development sub-type."""
    if sub_type == "PROPOSAL_PREP":
        for threshold, days in DEV_WORK_QUANTIFICATION["PROPOSAL_PREP"]["slabs"]:
            if proposal_value <= threshold:
                return days
        return 5
    elif sub_type == "EVENT_MGMT":
        return min(event_days, DEV_WORK_QUANTIFICATION["EVENT_MGMT"]["max_days"])
    elif sub_type == "COMMITTEE":
        return num_members * DEV_WORK_QUANTIFICATION["COMMITTEE"]["per_member_days"]
    elif sub_type == "MEETING":
        return max(event_days, DEV_WORK_QUANTIFICATION["MEETING"]["min_days"])
    return 0


def _parse_date(value):
    """Parse a date string or return None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_float(value, default=0.0):
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


def _parse_int(value, default=0):
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        return default


def _recalculate_assignment_progress(assignment):
    """Recalculate progress, invoice, payment, and revenue from milestones."""
    milestones = assignment.milestones.all()

    # Physical progress
    paid_pct = sum(
        float(m.revenue_percent or 0)
        for m in milestones if m.payment_received
    )
    pending_pct = sum(
        float(m.revenue_percent or 0) * 0.8
        for m in milestones if m.invoice_raised and not m.payment_received
    )
    physical_progress = paid_pct + pending_pct

    # Timeline progress
    total = milestones.count()
    if total > 0:
        completed = milestones.filter(status="Completed").count()
        delayed = milestones.filter(status="Delayed").count()
        timeline_progress = (completed / total) * 100
        if delayed:
            timeline_progress = max(0, timeline_progress - (delayed / total) * 20)
    else:
        timeline_progress = 0

    # Invoice and payment amounts
    total_value = assignment.total_value or assignment.gross_value or 0
    invoiced_pct = sum(
        float(m.revenue_percent or 0) for m in milestones if m.invoice_raised
    )
    paid_pct_full = sum(
        float(m.revenue_percent or 0) for m in milestones if m.payment_received
    )
    invoice_amount = total_value * invoiced_pct / 100
    amount_received = total_value * paid_pct_full / 100
    total_revenue = amount_received + (invoice_amount - amount_received) * 0.8

    assignment.physical_progress_percent = physical_progress
    assignment.timeline_progress_percent = timeline_progress
    assignment.invoice_amount = invoice_amount
    assignment.amount_received = amount_received
    assignment.total_revenue = total_revenue
    assignment.save(update_fields=[
        "physical_progress_percent", "timeline_progress_percent",
        "invoice_amount", "amount_received", "total_revenue",
    ])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@login_required
def register_activity(request):
    """GET: show registration form. POST: create minimal assignment."""
    if request.method == "GET":
        return render(request, "assignments/register_activity.html", {
            "error": request.GET.get("error", ""),
        })

    # POST
    title = request.POST.get("title", "").strip()
    activity_type = request.POST.get("type", "ASSIGNMENT")
    client = request.POST.get("client", "").strip()
    description = request.POST.get("description", "").strip()

    if not title:
        messages.error(request, "Title is required.")
        return redirect("core:register_activity")

    if activity_type not in ("ASSIGNMENT", "TRAINING", "DEVELOPMENT"):
        activity_type = "ASSIGNMENT"

    user = request.user
    office_id = user.office_id if hasattr(user, "office_id") else user.office.office_id

    assignment_no = _generate_assignment_number(office_id, activity_type, client)

    with transaction.atomic():
        assignment = Assignment.objects.create(
            assignment_no=assignment_no,
            type=activity_type,
            title=title,
            client=client,
            tor_scope=description,
            office_id=office_id,
            status="Not Started",
            registered_by=user,
            registration_status="PENDING_APPROVAL",
            workflow_stage="REGISTRATION",
            approval_status="DRAFT",
        )

        ApprovalRequest.objects.create(
            request_type="REGISTRATION",
            reference_type="assignment",
            reference_id=assignment.pk,
            requested_by=user,
            office_id=office_id,
            status="PENDING",
            request_data=f'{{"title": "{title}", "type": "{activity_type}", "client": "{client}"}}',
            remarks=f"New {activity_type.lower()} registration by {user.name}",
        )

        ActivityLog.objects.create(
            actor_id=user.officer_id,
            action="CREATE",
            entity_type="assignment",
            entity_id=str(assignment.pk),
            remarks=f"Registered new {activity_type.lower()}: {title}",
        )

    messages.success(request, "Activity registered successfully! Submitted for Head approval.")
    return redirect("core:assignment_view", assignment_id=assignment.pk)


# ---------------------------------------------------------------------------
# Work Orders List
# ---------------------------------------------------------------------------

@login_required
def workorders_list(request):
    """Display Work Orders list with filters."""
    user = request.user
    filter_view = request.GET.get("view", "")
    filter_office = request.GET.get("office", "")
    filter_status = request.GET.get("status", "")

    qs = Assignment.objects.select_related("team_leader", "office").all()

    if filter_view == "my_created":
        qs = qs.filter(team_leader=user.officer_id)
    elif filter_view == "my_office":
        qs = qs.filter(office=user.office.office_id)

    if filter_office:
        qs = qs.filter(office=filter_office)
    if filter_status:
        qs = qs.filter(status=filter_status)

    qs = qs.order_by("-created_at")

    # Status counts
    status_counts = dict(
        Assignment.objects.values_list("status")
        .annotate(cnt=Count("id"))
        .values_list("status", "cnt")
    )

    offices = Office.objects.order_by("office_id").values_list("office_id", "office_name")

    return render(request, "assignments/workorders_list.html", {
        "assignments": qs,
        "status_counts": status_counts,
        "offices": offices,
        "filter_view": filter_view,
        "filter_office": filter_office,
        "filter_status": filter_status,
    })


# ---------------------------------------------------------------------------
# Select Activity Type (for new creation flow)
# ---------------------------------------------------------------------------

@login_required
def select_activity_type(request):
    """Show activity type selection page."""
    return render(request, "assignments/select_activity_type.html")


# ---------------------------------------------------------------------------
# Select Type (for existing assignment without type)
# ---------------------------------------------------------------------------

@login_required
def select_type(request, assignment_id):
    """GET: show type picker. POST: set type and redirect to edit."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    if request.method == "POST":
        assignment_type = request.POST.get("assignment_type", "ASSIGNMENT")
        assignment.type = assignment_type
        assignment.save(update_fields=["type"])
        return redirect("core:assignment_edit", assignment_id=assignment.pk)

    if assignment.type:
        return redirect("core:assignment_edit", assignment_id=assignment.pk)

    return render(request, "assignments/select_type.html", {
        "assignment": assignment,
    })


# ---------------------------------------------------------------------------
# New Assignment
# ---------------------------------------------------------------------------

@login_required
def new_assignment(request):
    """GET: display form. POST: create assignment."""
    activity_type = request.GET.get("type", "ASSIGNMENT")
    if activity_type not in ("ASSIGNMENT", "DEVELOPMENT"):
        activity_type = "ASSIGNMENT"

    if request.method == "GET":
        officers = Officer.objects.filter(is_active=True).order_by("name")
        offices = Office.objects.order_by("office_id").values_list("office_id", flat=True)
        return render(request, "assignments/new_assignment_form.html", {
            "officers": officers,
            "offices": offices,
            "activity_type": activity_type,
            "status_options": _get_config_options("status"),
            "client_type_options": _get_config_options("client_type"),
            "domain_options": _get_config_options("domain"),
            "training_mode": TRAINING_MODE,
        })

    # POST — create
    user = request.user
    POST = request.POST
    assignment_type = POST.get("type", "ASSIGNMENT")
    office_id = POST.get("office_id", "")
    title = POST.get("title", "").strip()

    man_days = _parse_float(POST.get("man_days"))
    daily_rate = 0.20

    if assignment_type == "DEVELOPMENT":
        total_value = man_days * daily_rate
        is_notional = True
    else:
        total_value = _parse_float(POST.get("total_value"))
        is_notional = False

    if not title or not office_id:
        messages.error(request, "Title and Office are required.")
        return redirect(f"/assignment/new/?type={assignment_type}")

    client_name = POST.get("client", "")
    dev_sub_type = POST.get("dev_sub_type", "")
    proposal_value_lakhs = _parse_float(POST.get("proposal_value_lakhs"))
    num_committee_members = _parse_int(POST.get("num_committee_members"))
    event_duration_days = _parse_float(POST.get("event_duration_days"))

    if assignment_type == "DEVELOPMENT" and dev_sub_type and dev_sub_type != "OTHER":
        man_days = _calculate_dev_man_days(
            dev_sub_type,
            proposal_value=proposal_value_lakhs,
            num_members=num_committee_members,
            event_days=event_duration_days,
        )
        total_value = man_days * daily_rate

    assignment_no = _generate_assignment_number(office_id, assignment_type, client_name)

    with transaction.atomic():
        tl_id = POST.get("team_leader_officer_id") or None
        assignment = Assignment.objects.create(
            assignment_no=assignment_no,
            type=assignment_type,
            title=title,
            office_id=office_id,
            status=POST.get("status", "Not Started"),
            total_value=total_value,
            gross_value=total_value,
            client=client_name,
            client_type=POST.get("client_type", ""),
            city=POST.get("city", ""),
            domain=POST.get("domain", ""),
            sub_domain=POST.get("sub_domain", ""),
            work_order_date=_parse_date(POST.get("work_order_date")),
            start_date=_parse_date(POST.get("start_date")),
            target_date=_parse_date(POST.get("target_date")),
            team_leader_id=tl_id,
            tor_scope=POST.get("tor_scope", ""),
            man_days=man_days,
            daily_rate=daily_rate,
            is_notional=is_notional,
            dev_sub_type=dev_sub_type or "",
            proposal_value_lakhs=proposal_value_lakhs,
            num_committee_members=num_committee_members,
            event_duration_days=event_duration_days,
        )

        # Process inline milestones
        milestone_data = _collect_milestone_form_data(POST)
        milestone_no = 1
        for idx in sorted(milestone_data.keys()):
            data = milestone_data[idx]
            ms_title = data.get("title", "").strip()
            if ms_title:
                Milestone.objects.create(
                    assignment=assignment,
                    milestone_no=milestone_no,
                    title=ms_title,
                    description=data.get("description", ""),
                    target_date=_parse_date(data.get("target_date")),
                    revenue_percent=_parse_float(data.get("revenue_percent")),
                    status="Pending",
                )
                milestone_no += 1

    messages.success(request, "Assignment created successfully.")
    return redirect("core:manage_milestones", assignment_id=assignment.pk)


# ---------------------------------------------------------------------------
# Edit Assignment
# ---------------------------------------------------------------------------

@login_required
def edit_assignment(request, assignment_id):
    """GET: show edit form. POST: save changes."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    if not assignment.type:
        return redirect("core:select_type", assignment_id=assignment.pk)

    if request.method == "GET":
        officers = Officer.objects.filter(is_active=True).order_by("name")

        if assignment.type == "ASSIGNMENT":
            template_name = "assignments/assignment_form.html"
        elif assignment.type == "DEVELOPMENT":
            template_name = "assignments/assignment_form.html"  # reuse with conditional
        else:
            template_name = "assignments/assignment_form.html"

        return render(request, template_name, {
            "assignment": assignment,
            "officers": officers,
            "status_options": ASSIGNMENT_STATUS_OPTIONS,
            "client_type_options": CLIENT_TYPE_OPTIONS,
            "domain_options": DOMAIN_OPTIONS,
            "is_edit": True,
            "training_mode": TRAINING_MODE,
        })

    # POST — save
    POST = request.POST
    title = POST.get("title", "").strip()
    status = POST.get("status", assignment.status)

    # Reset basic info approval if it was previously approved
    if assignment.approval_status == "APPROVED":
        assignment.approval_status = "SUBMITTED"

    if assignment.type == "ASSIGNMENT":
        assignment.title = title
        assignment.tor_scope = POST.get("tor_scope", "")
        assignment.client = POST.get("client", "")
        assignment.client_type = POST.get("client_type", "")
        assignment.city = POST.get("city", "")
        assignment.domain = POST.get("domain", "")
        assignment.work_order_date = _parse_date(POST.get("work_order_date"))
        assignment.start_date = _parse_date(POST.get("start_date"))
        assignment.target_date = _parse_date(POST.get("target_date"))
        assignment.team_leader_id = POST.get("team_leader_officer_id") or None
        assignment.status = status
        assignment.details_filled = True

    elif assignment.type == "DEVELOPMENT":
        man_days_val = _parse_float(POST.get("man_days"))
        daily_rate_val = 0.20
        dev_sub = POST.get("dev_sub_type") or None
        prop_val = _parse_float(POST.get("proposal_value_lakhs"))
        num_members = _parse_int(POST.get("num_committee_members"))
        evt_days = _parse_float(POST.get("event_duration_days"))

        if dev_sub and dev_sub != "OTHER":
            man_days_val = _calculate_dev_man_days(
                dev_sub, proposal_value=prop_val,
                num_members=num_members, event_days=evt_days,
            )

        total_value = man_days_val * daily_rate_val
        assignment.title = title
        assignment.tor_scope = POST.get("tor_scope", "")
        assignment.client = POST.get("client", "")
        assignment.man_days = man_days_val
        assignment.daily_rate = daily_rate_val
        assignment.is_notional = True
        assignment.total_value = total_value
        assignment.gross_value = total_value
        assignment.start_date = _parse_date(POST.get("start_date"))
        assignment.target_date = _parse_date(POST.get("target_date"))
        assignment.team_leader_id = POST.get("team_leader_officer_id") or None
        assignment.status = status
        assignment.details_filled = True
        assignment.dev_sub_type = dev_sub or ""
        assignment.proposal_value_lakhs = prop_val
        assignment.num_committee_members = num_members
        assignment.event_duration_days = evt_days

    else:  # TRAINING
        assignment.title = title
        assignment.venue = POST.get("venue", "")
        assignment.duration_start = _parse_date(POST.get("duration_start"))
        assignment.duration_end = _parse_date(POST.get("duration_end"))
        assignment.duration_days = _parse_int(POST.get("duration_days"))
        assignment.type_of_participants = POST.get("type_of_participants", "")
        assignment.faculty1_id = POST.get("faculty1_officer_id") or None
        assignment.faculty2_id = POST.get("faculty2_officer_id") or None
        assignment.status = status
        assignment.details_filled = True

    assignment.save()
    messages.success(request, "Assignment details saved.")
    return redirect("core:dashboard")


# ---------------------------------------------------------------------------
# View Assignment (tabbed interface)
# ---------------------------------------------------------------------------

@login_required
def view_assignment(request, assignment_id):
    """View assignment details with tabbed interface."""
    assignment = get_object_or_404(
        Assignment.objects.select_related("office", "team_leader", "faculty1", "faculty2"),
        pk=assignment_id,
    )

    active_tab = request.GET.get("tab", "basic")
    if active_tab not in ("basic", "milestones", "cost", "team"):
        active_tab = "basic"

    cost_period = request.GET.get("cost_period", "all")

    # Officer names for header
    officers = {}
    if assignment.team_leader:
        officers["team_leader_officer_id"] = assignment.team_leader.name
    if assignment.faculty1:
        officers["faculty1_officer_id"] = assignment.faculty1.name
    if assignment.faculty2:
        officers["faculty2_officer_id"] = assignment.faculty2.name

    milestones = []
    revenue_shares = []
    expenditure_items = []
    expenditure_entries = []
    expenditure_heads = []
    computed = {}
    milestone_count = 0
    revenue_count = 0
    available_fys = []

    if active_tab == "basic":
        milestone_count = assignment.milestones.count()
        revenue_count = assignment.revenue_shares.count()

    elif active_tab == "milestones":
        milestones = list(assignment.milestones.order_by("milestone_no"))
        computed["total_revenue_pct"] = sum(
            float(m.revenue_percent or 0) for m in milestones
        )

    elif active_tab == "cost":
        expenditure_heads = list(
            ExpenditureHead.objects.filter(is_active=True).order_by("category", "head_code")
        )
        expenditure_items = list(
            ExpenditureItem.objects.filter(assignment=assignment)
            .select_related("head")
            .order_by("head__category", "head__head_code")
        )

        entries_qs = (
            ExpenditureEntry.objects.filter(assignment=assignment)
            .select_related("head", "entered_by")
            .order_by("-entry_date")
        )
        if cost_period and cost_period != "all":
            entries_qs = entries_qs.filter(fy_period=cost_period)
        expenditure_entries = list(entries_qs)

        available_fys = list(
            ExpenditureEntry.objects.filter(assignment=assignment)
            .values_list("fy_period", flat=True)
            .distinct()
            .order_by("fy_period")
        )

        computed["total_estimated"] = sum(
            float(i.estimated_amount or 0) for i in expenditure_items
        )
        computed["total_actual"] = sum(
            float(i.actual_amount or 0) for i in expenditure_items
        )
        computed["total_expense_entries"] = sum(
            float(e.amount or 0) for e in expenditure_entries
        )

    elif active_tab == "team":
        revenue_shares = list(
            RevenueShare.objects.filter(assignment=assignment)
            .select_related("officer")
            .order_by("-share_percent")
        )
        computed["total_share_pct"] = sum(
            float(s.share_percent or 0) for s in revenue_shares
        )
        computed["total_share_amt"] = sum(
            float(s.share_amount or 0) for s in revenue_shares
        )

    context = {
        "assignment": assignment,
        "officers": officers,
        "active_tab": active_tab,
        "milestones": milestones,
        "revenue_shares": revenue_shares,
        "expenditure_items": expenditure_items,
        "expenditure_entries": expenditure_entries,
        "expenditure_heads": expenditure_heads,
        "training_mode": TRAINING_MODE,
        "computed": computed,
        "milestone_count": milestone_count,
        "revenue_count": revenue_count,
        "cost_period": cost_period,
        "available_fys": available_fys,
    }
    return render(request, "assignments/assignment_view.html", context)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

def _collect_milestone_form_data(POST):
    """Parse milestone_X_field form fields into a dict keyed by index."""
    milestone_data = {}
    for key in POST:
        if key.startswith("milestone_"):
            parts = key.split("_")
            if len(parts) >= 3:
                idx = parts[1]
                field = "_".join(parts[2:])
                if idx not in milestone_data:
                    milestone_data[idx] = {}
                milestone_data[idx][field] = POST[key]
    return milestone_data


@login_required
def manage_milestones(request, assignment_id):
    """GET: show milestones form. POST: save milestones."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    if request.method == "GET":
        milestones = list(assignment.milestones.order_by("milestone_no"))
        return render(request, "assignments/milestones_form.html", {
            "assignment": assignment,
            "milestones": milestones,
            "training_mode": TRAINING_MODE,
        })

    # POST — save milestones
    POST = request.POST
    milestone_data = _collect_milestone_form_data(POST)

    with transaction.atomic():
        existing_ids = set(
            assignment.milestones.values_list("id", flat=True)
        )
        processed_ids = set()

        for idx, data in milestone_data.items():
            ms_title = data.get("title", "").strip()
            if not ms_title:
                continue

            milestone_id = data.get("id")
            invoice_raised = bool(data.get("invoice_raised"))
            payment_received = bool(data.get("payment_received"))

            if milestone_id and milestone_id.isdigit():
                milestone_id = int(milestone_id)
                processed_ids.add(milestone_id)

                Milestone.objects.filter(
                    pk=milestone_id, assignment=assignment
                ).update(
                    title=ms_title,
                    description=data.get("description", ""),
                    target_date=_parse_date(data.get("target_date")),
                    revenue_percent=_parse_float(data.get("revenue_percent")),
                    invoice_raised=invoice_raised,
                    invoice_raised_date=_parse_date(data.get("invoice_raised_date")),
                    payment_received=payment_received,
                    payment_received_date=_parse_date(data.get("payment_received_date")),
                    status=data.get("status", "Pending"),
                    remarks=data.get("remarks", ""),
                )
            else:
                # New milestone
                next_no = (
                    assignment.milestones.aggregate(
                        max_no=models_max("milestone_no")
                    )["max_no"]
                    or 0
                ) + 1

                target_dt = _parse_date(data.get("target_date"))
                Milestone.objects.create(
                    assignment=assignment,
                    milestone_no=next_no,
                    title=ms_title,
                    description=data.get("description", ""),
                    target_date=target_dt,
                    tentative_date=target_dt,
                    tentative_date_status="APPROVED",
                    revenue_percent=_parse_float(data.get("revenue_percent")),
                    invoice_raised=invoice_raised,
                    invoice_raised_date=_parse_date(data.get("invoice_raised_date")),
                    payment_received=payment_received,
                    payment_received_date=_parse_date(data.get("payment_received_date")),
                    status=data.get("status", "Pending"),
                    remarks=data.get("remarks", ""),
                )

        # Delete removed milestones
        ids_to_delete = existing_ids - processed_ids
        if ids_to_delete:
            Milestone.objects.filter(pk__in=ids_to_delete, assignment=assignment).delete()

        # Reset milestone approval if previously approved
        if assignment.milestone_approval_status == "APPROVED":
            assignment.milestone_approval_status = "SUBMITTED"
            assignment.save(update_fields=["milestone_approval_status"])

        # Recalculate progress
        _recalculate_assignment_progress(assignment)

    # Wizard flow
    next_step = POST.get("next_step", "")
    if next_step == "cost_estimate":
        return redirect("core:manage_expenditure", assignment_id=assignment.pk)

    messages.success(request, "Milestones saved.")
    return redirect("core:assignment_view", assignment_id=assignment.pk)


@login_required
def request_tentative_date_change(request, assignment_id):
    """POST: request tentative date change for a milestone."""
    if request.method != "POST":
        return redirect("core:manage_milestones", assignment_id=assignment_id)

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    user = request.user

    milestone_id = request.POST.get("milestone_id")
    new_tentative_date = request.POST.get("new_tentative_date")
    reason = request.POST.get("reason", "").strip()

    if not milestone_id or not new_tentative_date:
        return redirect("core:manage_milestones", assignment_id=assignment_id)

    Milestone.objects.filter(
        pk=milestone_id, assignment=assignment
    ).update(
        tentative_date=_parse_date(new_tentative_date),
        tentative_date_status="PENDING",
        tentative_date_reason=reason,
        tentative_date_requested_by=user.officer_id,
    )

    messages.info(request, "Tentative date change request submitted for approval.")
    return redirect("core:manage_milestones", assignment_id=assignment_id)


# ---------------------------------------------------------------------------
# Expenditure (Cost Estimate)
# ---------------------------------------------------------------------------

@login_required
def manage_expenditure(request, assignment_id):
    """GET: show expenditure form. POST: save expenditure estimates."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    if request.method == "GET":
        expenditure_heads = list(
            ExpenditureHead.objects.filter(is_active=True).order_by("category", "head_code")
        )
        existing_items = ExpenditureItem.objects.filter(assignment=assignment).select_related("head")
        existing_by_head = {item.head_id: item for item in existing_items}

        return render(request, "assignments/expenditure_form.html", {
            "assignment": assignment,
            "expenditure_heads": expenditure_heads,
            "existing_by_head": existing_by_head,
            "training_mode": TRAINING_MODE,
        })

    # POST — save
    POST = request.POST
    total_estimated = 0
    total_actual = 0

    with transaction.atomic():
        for key in POST:
            if key.startswith("estimated_"):
                head_id = int(key.replace("estimated_", ""))
                estimated = _parse_float(POST.get(key))
                actual = _parse_float(POST.get(f"actual_{head_id}"))
                remarks = POST.get(f"remarks_{head_id}", "")

                total_estimated += estimated
                total_actual += actual

                if estimated > 0 or actual > 0:
                    ExpenditureItem.objects.update_or_create(
                        assignment=assignment, head_id=head_id,
                        defaults={
                            "estimated_amount": estimated,
                            "actual_amount": actual,
                            "remarks": remarks,
                        },
                    )
                else:
                    ExpenditureItem.objects.filter(
                        assignment=assignment, head_id=head_id
                    ).delete()

        # Reset cost approval if previously approved
        update_fields = ["total_expenditure", "surplus_deficit"]
        assignment.total_expenditure = total_actual
        assignment.surplus_deficit = (assignment.total_revenue or 0) - total_actual
        if assignment.cost_approval_status == "APPROVED":
            assignment.cost_approval_status = "SUBMITTED"
            update_fields.append("cost_approval_status")
        assignment.save(update_fields=update_fields)

    # Wizard flow
    next_step = POST.get("next_step", "")
    if next_step == "team_revenue":
        return redirect("core:revenue_share_page", assignment_id=assignment.pk)

    messages.success(request, "Cost estimates saved.")
    return redirect("core:assignment_view", assignment_id=assignment.pk)


# ---------------------------------------------------------------------------
# Expenditure Entry (date-wise expense recording)
# ---------------------------------------------------------------------------

@login_required
def expenditure_entry(request, assignment_id):
    """GET: show expense entry form. POST: save entry."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    if request.method == "GET":
        expenditure_heads = list(
            ExpenditureHead.objects.filter(is_active=True).order_by("category", "head_code")
        )
        return render(request, "assignments/expenditure_entry_form.html", {
            "assignment": assignment,
            "expenditure_heads": expenditure_heads,
            "training_mode": TRAINING_MODE,
        })

    # POST
    user = request.user
    POST = request.POST
    head_id = _parse_int(POST.get("head_id"))
    entry_date = POST.get("entry_date", "")
    amount = _parse_float(POST.get("amount"))
    description = POST.get("description", "").strip()
    voucher_reference = POST.get("voucher_reference", "").strip()

    if not head_id or not entry_date or amount <= 0:
        messages.error(request, "Head, date, and a positive amount are required.")
        return redirect("core:expenditure_entry", assignment_id=assignment_id)

    fy_period = _get_fy_for_date(entry_date)

    with transaction.atomic():
        # Find or create parent expenditure item
        parent, _ = ExpenditureItem.objects.get_or_create(
            assignment=assignment, head_id=head_id,
            defaults={"estimated_amount": 0, "actual_amount": 0},
        )

        ExpenditureEntry.objects.create(
            expenditure_item=parent,
            assignment=assignment,
            head_id=head_id,
            entry_date=_parse_date(entry_date),
            amount=amount,
            fy_period=fy_period,
            description=description,
            voucher_reference=voucher_reference,
            entered_by=user,
        )

        # Update parent actual_amount from sum of entries
        entry_sum = (
            ExpenditureEntry.objects.filter(expenditure_item=parent)
            .aggregate(total=Sum("amount"))["total"]
            or 0
        )
        parent.actual_amount = entry_sum
        parent.save(update_fields=["actual_amount"])

        # Update assignment total_expenditure
        total_exp = (
            ExpenditureItem.objects.filter(assignment=assignment)
            .aggregate(total=Sum("actual_amount"))["total"]
            or 0
        )
        assignment.total_expenditure = total_exp
        assignment.surplus_deficit = (assignment.total_revenue or 0) - total_exp
        assignment.save(update_fields=["total_expenditure", "surplus_deficit"])

    messages.success(request, "Expense entry recorded.")
    return redirect("core:assignment_view", assignment_id=assignment.pk)


# ---------------------------------------------------------------------------
# Assignments List (MIS-style with filters & sorting)
# ---------------------------------------------------------------------------

@login_required
def assignments_list(request):
    """Display assignments list with filters and sorting."""
    filter_office = request.GET.get("filter_office", "")
    filter_domain = request.GET.get("filter_domain", "")
    filter_status = request.GET.get("filter_status", "")
    sort_by = request.GET.get("sort_by", "revenue")
    sort_order = request.GET.get("sort_order", "desc")

    qs = Assignment.objects.select_related("office", "team_leader").all()

    if filter_office:
        qs = qs.filter(office=filter_office)
    if filter_domain:
        qs = qs.filter(domain=filter_domain)
    if filter_status:
        qs = qs.filter(status=filter_status)

    # Annotate milestone counts
    qs = qs.annotate(
        milestone_count=Count("milestones"),
        paid_milestones=Count("milestones", filter=Q(milestones__payment_received=True)),
        invoiced_milestones=Count("milestones", filter=Q(milestones__invoice_raised=True)),
    )

    # Sorting
    sort_map = {
        "revenue": "total_revenue",
        "physical": "physical_progress_percent",
        "timeline": "timeline_progress_percent",
        "value": "total_value",
    }
    order_field = sort_map.get(sort_by, "total_revenue")
    if sort_order == "asc":
        qs = qs.order_by(F(order_field).asc(nulls_last=True))
    else:
        qs = qs.order_by(F(order_field).desc(nulls_last=True))

    # Options for filters
    offices = list(Office.objects.order_by("office_id").values_list("office_id", flat=True))
    domains = list(
        Assignment.objects.exclude(domain="")
        .values_list("domain", flat=True)
        .distinct()
        .order_by("domain")
    )
    statuses = [s[0] for s in Assignment.Status.choices]

    return render(request, "assignments/assignments_list.html", {
        "assignments": qs,
        "offices": offices,
        "domains": domains,
        "statuses": statuses,
        "filter_office": filter_office,
        "filter_domain": filter_domain,
        "filter_status": filter_status,
        "sort_by": sort_by,
        "sort_order": sort_order,
    })


@login_required
def head_assignment_hub(request):
    """Assignment hub for RD Heads and Group Heads.

    Shows all assignments for their office with:
    - TL allocation action
    - Delist/transfer action
    - Edit financial data action
    - Summary stats
    """
    user = request.user
    office_id = user.office_id
    role = getattr(user, "admin_role_id", "") or ""

    # Get assignments for this office
    qs = Assignment.objects.filter(office_id=office_id).select_related("office", "team_leader")

    # Handle actions via POST
    if request.method == "POST":
        action = request.POST.get("action")
        assignment_id = request.POST.get("assignment_id")

        # ── Action 1: Assign Team Leader ──
        if action == "assign_tl" and assignment_id:
            tl_id = request.POST.get("team_leader_id")
            try:
                assignment = Assignment.objects.get(id=assignment_id, office_id=office_id)
                if tl_id:
                    tl = Officer.objects.get(officer_id=tl_id)
                    assignment.team_leader = tl
                    if assignment.workflow_stage == "REGISTRATION":
                        assignment.workflow_stage = "TL_ASSIGNMENT"
                    assignment.save(update_fields=["team_leader", "workflow_stage"])
                    messages.success(request, f"Team Leader '{tl.name}' assigned to '{assignment.title[:50]}'")
                else:
                    assignment.team_leader = None
                    assignment.save(update_fields=["team_leader"])
                    messages.info(request, f"Team Leader removed from '{assignment.title[:50]}'")
            except (Assignment.DoesNotExist, Officer.DoesNotExist) as e:
                messages.error(request, f"Error: {e}")

        # ── Action 2: Mark Not Assignment (with remark for admin) ──
        elif action == "mark_not_assignment" and assignment_id:
            remark = request.POST.get("remark", "").strip()
            try:
                assignment = Assignment.objects.get(id=assignment_id, office_id=office_id)
                assignment.status = "On Hold"
                assignment.tor_scope = f"[NOT AN ASSIGNMENT - Head Remark]: {remark}\n\n{assignment.tor_scope or ''}"
                assignment.save(update_fields=["status", "tor_scope"])
                messages.warning(request, f"'{assignment.title[:40]}' marked as not-assignment. Admin will review.")
            except Assignment.DoesNotExist:
                messages.error(request, "Assignment not found")

        # ── Action 3: Merge multiple assignments into one ──
        elif action == "merge":
            merge_ids = request.POST.getlist("merge_ids")
            primary_id = request.POST.get("primary_id")
            if len(merge_ids) >= 2 and primary_id:
                try:
                    with transaction.atomic():
                        primary = Assignment.objects.get(id=primary_id, office_id=office_id)
                        others = Assignment.objects.filter(
                            id__in=merge_ids, office_id=office_id
                        ).exclude(id=primary_id)

                        merged_names = []
                        for other in others:
                            # Sum financials into primary
                            primary.invoice_amount = (primary.invoice_amount or 0) + (other.invoice_amount or 0)
                            primary.amount_received = (primary.amount_received or 0) + (other.amount_received or 0)
                            primary.total_expenditure = (primary.total_expenditure or 0) + (other.total_expenditure or 0)
                            primary.total_value = (primary.total_value or 0) + (other.total_value or 0)
                            primary.gross_value = (primary.gross_value or 0) + (other.gross_value or 0)
                            # Move invoices and receipts to primary
                            from core.models import InvoiceRequest, PaymentReceipt
                            InvoiceRequest.objects.filter(assignment=other).update(assignment=primary)
                            merged_names.append(other.title[:30])
                            # Mark other as cancelled with merge note
                            other.status = "Cancelled"
                            other.tor_scope = f"[MERGED INTO {primary.assignment_no}]\n{other.tor_scope or ''}"
                            other.save()

                        primary.tor_scope = f"[MERGED FROM: {', '.join(merged_names)}]\n{primary.tor_scope or ''}"
                        primary.save()
                        messages.success(request, f"Merged {len(others)} assignments into '{primary.title[:40]}'")
                except Exception as e:
                    messages.error(request, f"Merge error: {e}")
            else:
                messages.error(request, "Select at least 2 assignments and choose a primary to merge.")

        # ── Action 4: Delist / wrong office ──
        elif action == "delist" and assignment_id:
            remark = request.POST.get("remark", "").strip()
            try:
                assignment = Assignment.objects.get(id=assignment_id, office_id=office_id)
                assignment.status = "Cancelled"
                assignment.tor_scope = f"[DELISTED BY HEAD - Wrong Office]: {remark}\n{assignment.tor_scope or ''}"
                assignment.save(update_fields=["status", "tor_scope"])
                messages.warning(request, f"'{assignment.title[:40]}' delisted. Admin will reassign.")
            except Assignment.DoesNotExist:
                messages.error(request, "Assignment not found")

        # ── Action 5: Confirm assignment (data is correct, ready for TL) ──
        elif action == "confirm" and assignment_id:
            try:
                assignment = Assignment.objects.get(id=assignment_id, office_id=office_id)
                assignment.registration_status = "APPROVED"
                assignment.approval_status = "APPROVED"
                # Only flag as bulk-onboarded while the onboarding window is
                # open (SCOPE_V2 §3.6). After window close, confirmed
                # assignments follow the normal fresh-registration path.
                window_open = SiteConfig.bulk_window_is_open()
                if window_open:
                    assignment.is_bulk_onboarded = True
                if assignment.team_leader:
                    assignment.workflow_stage = "DETAIL_ENTRY"
                assignment.save(update_fields=[
                    "registration_status", "approval_status", "workflow_stage",
                    "is_bulk_onboarded",
                ])
                if window_open:
                    messages.success(request, f"'{assignment.title[:40]}' confirmed. TL can now fill retrospective details.")
                else:
                    messages.success(request, f"'{assignment.title[:40]}' confirmed. Bulk-onboarding window is closed — TL follows the fresh registration flow.")
            except Assignment.DoesNotExist:
                messages.error(request, "Assignment not found")

        return redirect("core:head_hub")

    # Filters
    filter_status = request.GET.get("status", "")
    filter_tl = request.GET.get("tl", "")
    if filter_status:
        qs = qs.filter(status=filter_status)
    if filter_tl == "unassigned":
        qs = qs.filter(team_leader__isnull=True)
    elif filter_tl == "assigned":
        qs = qs.filter(team_leader__isnull=False)

    qs = qs.order_by("-invoice_amount")

    # Officers in this office (for TL dropdown)
    office_officers = Officer.objects.filter(office_id=office_id, is_active=True).order_by("name")

    # Additional filters
    filter_review = request.GET.get("review", "")
    if filter_review == "pending":
        qs = qs.filter(status__in=["Ongoing", "Not Started", "Completed"]).exclude(
            workflow_stage="DETAIL_ENTRY")
    elif filter_review == "confirmed":
        qs = qs.filter(workflow_stage__in=["DETAIL_ENTRY", "ACTIVE", "COMPLETED"])
    elif filter_review == "flagged":
        qs = qs.filter(status__in=["On Hold", "Cancelled"])

    # Summary stats
    all_office_qs = Assignment.objects.filter(office_id=office_id)
    total_count = all_office_qs.count()
    active_qs = all_office_qs.exclude(status__in=["Cancelled", "On Hold"])
    tl_assigned = active_qs.filter(team_leader__isnull=False).count()
    tl_unassigned = active_qs.filter(team_leader__isnull=True).count()
    confirmed_count = all_office_qs.filter(workflow_stage__in=["DETAIL_ENTRY", "ACTIVE", "COMPLETED"]).count()
    flagged_count = all_office_qs.filter(status__in=["On Hold", "Cancelled"]).count()
    pending_review = total_count - confirmed_count - flagged_count
    total_invoiced = active_qs.aggregate(s=Sum("invoice_amount"))["s"] or 0
    total_received = qs.aggregate(s=Sum("amount_received"))["s"] or 0

    return render(request, "assignments/head_hub.html", {
        "assignments": qs,
        "office_officers": office_officers,
        "office_id": office_id,
        "role": role,
        "user": user,
        "total_count": total_count,
        "tl_assigned": tl_assigned,
        "tl_unassigned": tl_unassigned,
        "confirmed_count": confirmed_count,
        "flagged_count": flagged_count,
        "pending_review": pending_review,
        "total_invoiced": total_invoiced,
        "total_received": total_received,
        "filter_status": filter_status,
        "filter_tl": filter_tl,
        "filter_review": filter_review,
        "bulk_window_open": SiteConfig.bulk_window_is_open(),
        "bulk_window_close_date": SiteConfig.bulk_window_close_date(),
    })


def _derive_fy(d):
    """Indian financial year label for a date, e.g. 2025-04-01 -> '2025-26'."""
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    return f"{d.year - 1}-{str(d.year)[2:]}"


def _refresh_assignment_financial_sums(assignment):
    """Recompute cached invoice_amount and amount_received from child records."""
    invoiced = InvoiceRequest.objects.filter(
        assignment=assignment, status="INVOICED",
    ).aggregate(s=Sum("invoice_amount"))["s"] or 0
    received = PaymentReceipt.objects.filter(
        invoice_request__assignment=assignment,
    ).aggregate(s=Sum("amount_received"))["s"] or 0
    assignment.invoice_amount = invoiced
    assignment.amount_received = received
    assignment.save(update_fields=["invoice_amount", "amount_received"])


@login_required
def retrospective_fill(request, assignment_id):
    """Retrospective data entry for bulk-onboarded assignments (SCOPE_V2 §3.6).

    Actions (POST):
      - save_meta (default): as-of date + physical progress %
      - add_invoice: create InvoiceRequest with status=INVOICED (bypasses FSM
        intentionally — historic data has no approval step in real life).
        OfficerRevenueLedger backfill is deferred to Slice D.3.
      - add_payment: create PaymentReceipt linked to an existing invoice.

    Accessible to the assignment's TL, the office's RD/GH, or admin. Refuses
    when the assignment is not is_bulk_onboarded.
    """
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    user = request.user
    role = getattr(user, "admin_role_id", "") or ""

    is_tl = assignment.team_leader_id == user.officer_id
    is_office_head = (
        role in ("ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD")
        and assignment.office_id == user.office_id
    )
    is_admin = user.is_staff or role == "ADMIN"
    if not (is_tl or is_office_head or is_admin):
        messages.error(request, "You do not have access to this assignment.")
        return redirect("core:dashboard")

    if not assignment.is_bulk_onboarded:
        messages.info(request, "This assignment is not bulk-onboarded; retrospective fill does not apply.")
        return redirect("core:assignment_view", assignment_id=assignment_id)

    if request.method == "POST":
        action = request.POST.get("action", "save_meta")

        if action == "save_meta":
            as_of_raw = request.POST.get("as_of_date", "").strip()
            phys_raw = request.POST.get("physical_progress_percent", "").strip()
            update_fields = []
            if as_of_raw:
                try:
                    assignment.bulk_onboarding_as_of_date = datetime.strptime(as_of_raw, "%Y-%m-%d").date()
                    update_fields.append("bulk_onboarding_as_of_date")
                except ValueError:
                    messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
                    return redirect("core:retrospective_fill", assignment_id=assignment_id)
            if phys_raw:
                try:
                    phys = float(phys_raw)
                except ValueError:
                    messages.error(request, "Physical progress must be a number.")
                    return redirect("core:retrospective_fill", assignment_id=assignment_id)
                if not (0 <= phys <= 100):
                    messages.error(request, "Physical progress must be between 0 and 100.")
                    return redirect("core:retrospective_fill", assignment_id=assignment_id)
                assignment.physical_progress_percent = phys
                update_fields.append("physical_progress_percent")
            if update_fields:
                assignment.save(update_fields=update_fields)
                ActivityLog.objects.create(
                    actor=user, action="UPDATE", entity_type="assignment",
                    entity_id=assignment.pk,
                    remarks=f"Retrospective meta: as_of={as_of_raw or '-'}, phys={phys_raw or '-'}",
                )
                messages.success(request, "Retrospective data saved.")

        elif action == "add_invoice":
            try:
                amount = float(request.POST.get("invoice_amount", "0"))
                invoice_date = datetime.strptime(
                    request.POST.get("invoice_date", "").strip(), "%Y-%m-%d",
                ).date()
            except (ValueError, TypeError):
                messages.error(request, "Invoice amount and date are required.")
                return redirect("core:retrospective_fill", assignment_id=assignment_id)
            if amount <= 0:
                messages.error(request, "Invoice amount must be positive.")
                return redirect("core:retrospective_fill", assignment_id=assignment_id)

            external_ref = request.POST.get("invoice_reference", "").strip()
            invoice_type = request.POST.get("invoice_type", "SUBSEQUENT")
            if invoice_type not in ("ADVANCE", "SUBSEQUENT", "FINAL"):
                invoice_type = "SUBSEQUENT"

            seq = InvoiceRequest.objects.filter(assignment=assignment).count() + 1
            with transaction.atomic():
                invoice = InvoiceRequest(
                    request_number=f"LEGACY/{assignment.assignment_no}/{seq:02d}",
                    assignment=assignment,
                    invoice_type=invoice_type,
                    invoice_amount=amount,
                    fy_period=_derive_fy(invoice_date),
                    description=f"Historic invoice (bulk onboarding). External ref: {external_ref or '-'}",
                    status="INVOICED",  # bypass FSM — historic data has no approval
                    requested_by=user,
                    tally_invoice_date=invoice_date,
                    revenue_recognized_80=round(amount * 0.80, 2),
                )
                invoice.save()
                _refresh_assignment_financial_sums(assignment)
            ActivityLog.objects.create(
                actor=user, action="CREATE", entity_type="invoice_request",
                entity_id=invoice.pk,
                remarks=f"Historic invoice added: {invoice.request_number} amt={amount}",
            )
            messages.success(request, f"Historic invoice {invoice.request_number} recorded.")

        elif action == "add_payment":
            invoice_id = request.POST.get("invoice_id", "")
            try:
                amount = float(request.POST.get("payment_amount", "0"))
                payment_date = datetime.strptime(
                    request.POST.get("payment_date", "").strip(), "%Y-%m-%d",
                ).date()
            except (ValueError, TypeError):
                messages.error(request, "Payment amount and date are required.")
                return redirect("core:retrospective_fill", assignment_id=assignment_id)
            if amount <= 0:
                messages.error(request, "Payment amount must be positive.")
                return redirect("core:retrospective_fill", assignment_id=assignment_id)

            try:
                invoice = InvoiceRequest.objects.get(pk=invoice_id, assignment=assignment)
            except (InvoiceRequest.DoesNotExist, ValueError):
                messages.error(request, "Select a valid invoice to receive payment against.")
                return redirect("core:retrospective_fill", assignment_id=assignment_id)

            payment_mode = request.POST.get("payment_mode", "").strip().upper()
            if payment_mode not in ("NEFT", "RTGS", "CHEQUE", "DD", "CASH", "UPI", ""):
                payment_mode = ""
            reference = request.POST.get("payment_reference", "").strip()

            seq = PaymentReceipt.objects.filter(invoice_request=invoice).count() + 1
            with transaction.atomic():
                receipt = PaymentReceipt(
                    receipt_number=f"LEGACY/{invoice.request_number}/P{seq:02d}",
                    invoice_request=invoice,
                    amount_received=amount,
                    receipt_date=payment_date,
                    payment_mode=payment_mode,
                    reference_number=reference,
                    fy_period=_derive_fy(payment_date),
                    remarks="Historic payment (bulk onboarding)",
                    updated_by=user,
                )
                receipt.save()  # save() auto-calculates revenue_recognized_20
                _refresh_assignment_financial_sums(assignment)
            ActivityLog.objects.create(
                actor=user, action="CREATE", entity_type="payment_receipt",
                entity_id=receipt.pk,
                remarks=f"Historic payment added: {receipt.receipt_number} amt={amount}",
            )
            messages.success(request, f"Historic payment {receipt.receipt_number} recorded.")

        return redirect("core:retrospective_fill", assignment_id=assignment_id)

    invoices = InvoiceRequest.objects.filter(assignment=assignment).order_by("-tally_invoice_date", "-id")
    payments = PaymentReceipt.objects.filter(
        invoice_request__assignment=assignment,
    ).select_related("invoice_request").order_by("-receipt_date", "-id")

    return render(request, "assignments/retrospective_fill.html", {
        "assignment": assignment,
        "can_edit": is_tl or is_office_head or is_admin,
        "invoices": invoices,
        "payments": payments,
    })


# We need Max import for milestone numbering
from django.db.models import Max as models_max  # noqa: E402
