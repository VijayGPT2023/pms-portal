"""
Report views: Delay Tracking, Physical Progress MIS, Financial Progress MIS.
"""
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Q, Sum, Case, When, Value, IntegerField
from django.db.models.functions import Now
from django.http import JsonResponse
from django.shortcuts import redirect, render

from core.models import (
    Assignment, ExpenditureEntry, ExpenditureHead, ExpenditureItem,
    InvoiceRequest, Milestone, Office, PaymentReceipt,
)


def _traffic_light(days):
    """Return traffic light color based on delay days."""
    if days is None:
        return "green"
    if days < 30:
        return "green"
    elif days < 60:
        return "amber"
    return "red"


@login_required
def delay_dashboard(request):
    """Main delay tracking dashboard with 4 delay categories."""
    office_filter = request.GET.get("office")
    today = date.today()

    base_assignment_q = Q()
    if office_filter:
        base_assignment_q = Q(assignment__office__office_id=office_filter)

    base_q = Q()
    if office_filter:
        base_q = Q(office__office_id=office_filter)

    # A. Payment Delays: invoices approved but no payment received
    payment_delays = (
        InvoiceRequest.objects.filter(
            Q(status__in=["APPROVED", "INVOICED"]),
            Q(payments__isnull=True),
            Q(approved_at__isnull=False),
            base_assignment_q,
        )
        .select_related("assignment")
        .annotate(delay_days=Value(0, output_field=IntegerField()))  # placeholder
        .order_by("-approved_at")[:50]
    )
    # Calculate delay days in Python since DB-agnostic
    payment_delays_list = []
    for ir in payment_delays:
        if ir.approved_at:
            days = (today - ir.approved_at.date()).days
            payment_delays_list.append({
                "id": ir.pk,
                "request_number": ir.request_number,
                "invoice_amount": ir.invoice_amount,
                "approved_at": ir.approved_at,
                "assignment_no": ir.assignment.assignment_no if ir.assignment else "",
                "title": ir.assignment.title if ir.assignment else "",
                "office_id": ir.assignment.office_id if ir.assignment else "",
                "delay_days": days,
                "color": _traffic_light(days),
            })

    # B. Invoice Delays: milestones past target_date but invoice not raised
    invoice_delays_qs = Milestone.objects.filter(
        target_date__lt=today,
        invoice_raised=False,
    ).exclude(status="Cancelled")
    if office_filter:
        invoice_delays_qs = invoice_delays_qs.filter(assignment__office__office_id=office_filter)

    invoice_delays_list = []
    for m in invoice_delays_qs.select_related("assignment")[:50]:
        days = (today - m.target_date).days if m.target_date else 0
        invoice_delays_list.append({
            "milestone_no": m.milestone_no,
            "milestone_title": m.title,
            "target_date": m.target_date,
            "assignment_no": m.assignment.assignment_no,
            "title": m.assignment.title,
            "office_id": m.assignment.office_id,
            "delay_days": days,
            "color": _traffic_light(days),
        })

    # C. Milestone Delays: past target_date but not completed
    milestone_delays_qs = Milestone.objects.filter(
        target_date__lt=today,
    ).exclude(status__in=["Completed", "Cancelled"])
    if office_filter:
        milestone_delays_qs = milestone_delays_qs.filter(assignment__office__office_id=office_filter)

    milestone_delays_list = []
    for m in milestone_delays_qs.select_related("assignment")[:50]:
        days = (today - m.target_date).days if m.target_date else 0
        milestone_delays_list.append({
            "milestone_no": m.milestone_no,
            "milestone_title": m.title,
            "target_date": m.target_date,
            "status": m.status,
            "assignment_no": m.assignment.assignment_no,
            "title": m.assignment.title,
            "office_id": m.assignment.office_id,
            "delay_days": days,
            "color": _traffic_light(days),
        })

    # D. Activation Delays: stuck in early workflow stages > 30 days
    threshold = today - timedelta(days=30)
    activation_qs = Assignment.objects.filter(
        workflow_stage__in=["REGISTRATION", "TL_ASSIGNMENT", "DETAIL_ENTRY"],
        created_at__date__lt=threshold,
    )
    if office_filter:
        activation_qs = activation_qs.filter(office__office_id=office_filter)

    activation_delays_list = []
    for a in activation_qs[:50]:
        days = (today - a.created_at.date()).days
        activation_delays_list.append({
            "id": a.pk,
            "assignment_no": a.assignment_no,
            "title": a.title,
            "office_id": a.office_id,
            "workflow_stage": a.workflow_stage,
            "delay_days": days,
            "color": _traffic_light(days),
        })

    offices = Office.objects.order_by("office_name")

    return render(request, "reports/delays.html", {
        "payment_delays": payment_delays_list,
        "invoice_delays": invoice_delays_list,
        "milestone_delays": milestone_delays_list,
        "activation_delays": activation_delays_list,
        "filter_office": office_filter,
        "offices": offices,
    })


@login_required
def delay_summary_api(request):
    """JSON API for delay summary counts."""
    office = request.GET.get("office")
    today = date.today()

    base_q = Q()
    if office:
        base_q = Q(assignment__office__office_id=office)

    payment_delays = InvoiceRequest.objects.filter(
        base_q,
        status__in=["APPROVED", "INVOICED"],
        payments__isnull=True,
    ).count()

    ms_base = Q(target_date__lt=today)
    if office:
        ms_base &= Q(assignment__office__office_id=office)

    invoice_delays = Milestone.objects.filter(
        ms_base, invoice_raised=False,
    ).exclude(status="Cancelled").count()

    milestone_delays = Milestone.objects.filter(
        ms_base,
    ).exclude(status__in=["Completed", "Cancelled"]).count()

    threshold = today - timedelta(days=30)
    act_q = Q(
        workflow_stage__in=["REGISTRATION", "TL_ASSIGNMENT", "DETAIL_ENTRY"],
        created_at__date__lt=threshold,
    )
    if office:
        act_q &= Q(office__office_id=office)
    activation_delays = Assignment.objects.filter(act_q).count()

    return JsonResponse({
        "payment_delays": payment_delays,
        "invoice_delays": invoice_delays,
        "milestone_delays": milestone_delays,
        "activation_delays": activation_delays,
        "total": payment_delays + invoice_delays + milestone_delays + activation_delays,
    })


@login_required
def physical_progress(request):
    """Physical progress report by office/domain/officer/type."""
    view = request.GET.get("view", "office")
    type_filter = request.GET.get("type")

    qs = Assignment.objects.all()
    if type_filter:
        qs = qs.filter(type=type_filter)

    if view == "office":
        progress_data = (
            qs.values("office__office_id", "office__office_name")
            .annotate(
                total_assignments=Count("id"),
                avg_physical_progress=Avg("physical_progress_percent"),
                avg_timeline_progress=Avg("timeline_progress_percent"),
                completed=Count("id", filter=Q(status="Completed")),
                active=Count("id", filter=Q(status__in=["Ongoing", "In Progress", "Not Started"])),
            )
            .filter(total_assignments__gt=0)
            .order_by("-avg_physical_progress")
        )
    elif view == "domain":
        progress_data = (
            qs.filter(domain__isnull=False)
            .values("domain")
            .annotate(
                total_assignments=Count("id"),
                avg_physical_progress=Avg("physical_progress_percent"),
                avg_timeline_progress=Avg("timeline_progress_percent"),
                completed=Count("id", filter=Q(status="Completed")),
                active=Count("id", filter=Q(status__in=["Ongoing", "In Progress", "Not Started"])),
            )
            .order_by("-avg_physical_progress")
        )
    elif view == "type":
        progress_data = (
            qs.filter(type__isnull=False)
            .values("type")
            .annotate(
                total_assignments=Count("id"),
                avg_physical_progress=Avg("physical_progress_percent"),
                avg_timeline_progress=Avg("timeline_progress_percent"),
                completed=Count("id", filter=Q(status="Completed")),
                active=Count("id", filter=Q(status__in=["Ongoing", "In Progress", "Not Started"])),
            )
        )
    else:
        progress_data = []

    offices = Office.objects.order_by("office_name")

    return render(request, "reports/physical_progress.html", {
        "progress_data": progress_data,
        "view": view,
        "filter_type": type_filter,
        "offices": offices,
    })


@login_required
def financial_progress(request):
    """Financial progress report."""
    view = request.GET.get("view", "office")

    if view == "office":
        financial_data = (
            Assignment.objects.values("office__office_id", "office__office_name")
            .annotate(
                total_value=Sum("total_value"),
                total_invoiced=Sum("invoice_amount"),
                total_received=Sum("amount_received"),
                sum_expenditure=Sum("total_expenditure"),
                sum_received=Sum("amount_received"),
                assignment_count=Count("id"),
            )
            .filter(assignment_count__gt=0)
            .order_by("-total_value")
        )
    elif view == "domain":
        financial_data = (
            Assignment.objects.filter(domain__isnull=False)
            .values("domain")
            .annotate(
                total_value=Sum("total_value"),
                total_invoiced=Sum("invoice_amount"),
                total_received=Sum("amount_received"),
                sum_expenditure=Sum("total_expenditure"),
                sum_received=Sum("amount_received"),
                assignment_count=Count("id"),
            )
            .order_by("-total_value")
        )
    else:
        financial_data = (
            Assignment.objects.filter(type__isnull=False)
            .values("type")
            .annotate(
                total_value=Sum("total_value"),
                total_invoiced=Sum("invoice_amount"),
                total_received=Sum("amount_received"),
                sum_expenditure=Sum("total_expenditure"),
                sum_received=Sum("amount_received"),
                assignment_count=Count("id"),
            )
        )

    # Expenditure breakdown
    expenditure_breakdown = (
        ExpenditureHead.objects.annotate(
            budgeted=Sum("expenditureitem__estimated_amount"),
            actual_spent=Sum("expenditureitem__actual_amount"),
        )
        .filter(Q(budgeted__gt=0) | Q(actual_spent__gt=0))
        .order_by("category")
    )

    # Grand totals
    totals = Assignment.objects.aggregate(
        grand_value=Sum("total_value"),
        grand_invoiced=Sum("invoice_amount"),
        grand_received=Sum("amount_received"),
        grand_expenditure=Sum("total_expenditure"),
    )
    totals["grand_net"] = (totals["grand_received"] or 0) - (totals["grand_expenditure"] or 0)

    offices = Office.objects.order_by("office_name")

    return render(request, "reports/financial_progress.html", {
        "financial_data": financial_data,
        "expenditure_breakdown": expenditure_breakdown,
        "totals": totals,
        "view": view,
        "offices": offices,
    })


@login_required
def dashboard_summary_api(request):
    """Key tracking metrics for embedding on top of main dashboard."""
    office = request.GET.get("office")
    today = date.today()

    a_q = Q()
    if office:
        a_q = Q(office__office_id=office)

    # Delay counts
    payment_delays = InvoiceRequest.objects.filter(
        status__in=["APPROVED", "INVOICED"],
        payments__isnull=True,
    ).count()

    ms_base = Q(target_date__lt=today)
    if office:
        ms_base &= Q(assignment__office__office_id=office)

    milestone_delays = Milestone.objects.filter(ms_base).exclude(
        status__in=["Completed", "Cancelled"]
    ).count()

    # Physical progress
    phys = Assignment.objects.filter(a_q).aggregate(
        avg_pct=Avg("physical_progress_percent"),
        completed=Count("id", filter=Q(status="Completed")),
    )

    # Financial summary
    fin = Assignment.objects.filter(a_q).aggregate(
        total_value=Sum("total_value"),
        invoiced=Sum("invoice_amount"),
        received=Sum("amount_received"),
        expenditure=Sum("total_expenditure"),
    )

    return JsonResponse({
        "delays": {
            "payment": payment_delays,
            "milestone": milestone_delays,
        },
        "physical_progress": {
            "avg_percent": round(phys["avg_pct"] or 0, 1),
            "completed": phys["completed"] or 0,
        },
        "financial": {
            "total_value": round(fin["total_value"] or 0, 2),
            "invoiced": round(fin["invoiced"] or 0, 2),
            "received": round(fin["received"] or 0, 2),
            "expenditure": round(fin["expenditure"] or 0, 2),
            "net": round((fin["received"] or 0) - (fin["expenditure"] or 0), 2),
        },
    })
