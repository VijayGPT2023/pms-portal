"""
MIS Analytics Command Center: 6-tab dashboard with Chart.js visualizations.
Tabs: Executive Summary, Office Performance, Activity & Domain, Financial Deep-Dive,
      Delays & Alerts, Officer & Client.
"""
import csv
import io
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Q, Sum, Value
from django.http import HttpResponse
from django.shortcuts import redirect, render

from core.models import (
    Assignment, AssignmentClient, Client, ExpenditureHead, ExpenditureItem,
    FinancialYearTarget, InvoiceRequest, Milestone, NonRevenueSuggestion,
    Office, Officer, PaymentReceipt, RevenueShare,
)

VALID_TABS = {"executive", "office", "activity", "financial", "delays", "officer_client"}


def _get_financial_years():
    """Generate list of financial years for filter dropdown."""
    current_year = date.today().year
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(current_year - 5, current_year + 2)]


def _default_fy():
    today = date.today()
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[-2:]}"
    return f"{today.year - 1}-{str(today.year)[-2:]}"


def _fy_progress():
    """Calculate how much of the financial year has elapsed."""
    today = date.today()
    if today.month >= 4:
        fy_start = date(today.year, 4, 1)
    else:
        fy_start = date(today.year - 1, 4, 1)
    fy_end = date(fy_start.year + 1, 3, 31)
    total_days = (fy_end - fy_start).days
    elapsed_days = (today - fy_start).days
    return min(elapsed_days / total_days, 1.0)


def _can_see_rankings(user):
    return user.admin_role_id in ("ADMIN", "DG", "DDG-I", "DDG-II") or user.is_staff


def _build_base_qs(financial_year, filter_office, filter_domain, filter_type):
    """Build base Assignment queryset with filters."""
    qs = Assignment.objects.all()
    if filter_office:
        qs = qs.filter(office__office_id=filter_office)
    if filter_domain:
        qs = qs.filter(domain=filter_domain)
    if filter_type:
        qs = qs.filter(type=filter_type)
    return qs


def _load_office_data(qs, financial_year, fy_progress_val, can_rank):
    """Load office-wise target vs achievement data."""
    office_agg = (
        qs.values("office__office_id", "office__office_name", "office__officer_count", "office__annual_revenue_target")
        .annotate(
            assignment_count=Count("id"),
            sum_revenue=Sum("total_revenue"),
            sum_assignment_revenue=Sum("total_revenue", filter=Q(type="ASSIGNMENT")),
            sum_training_revenue=Sum("total_revenue", filter=Q(type="TRAINING")),
            deposits=Sum("amount_received"),
            sum_expenditure=Sum("total_expenditure"),
            sum_surplus=Sum("surplus_deficit"),
            project_count=Count("id", filter=Q(type="ASSIGNMENT")),
            training_count=Count("id", filter=Q(type="TRAINING")),
            avg_physical_progress=Avg("physical_progress_percent"),
        )
        .filter(assignment_count__gt=0)
        .order_by("-total_revenue")
    )

    # Get notional revenue per office
    notional_by_office = dict(
        NonRevenueSuggestion.objects.filter(status="COMPLETED")
        .values_list("office__office_id")
        .annotate(nr=Sum("notional_value"))
        .values_list("office__office_id", "nr")
    )

    # Get FY targets
    targets = dict(
        FinancialYearTarget.objects.filter(financial_year=financial_year)
        .values_list("office__office_id", "annual_target")
    )

    office_data = []
    for o in office_agg:
        oid = o["office__office_id"]
        target = targets.get(oid, o["office__annual_revenue_target"] or 0)
        notional = notional_by_office.get(oid, 0) or 0
        rev = (o["sum_revenue"] or 0)
        contribution = rev * settings.REVENUE_WEIGHTAGE_REAL + notional * settings.REVENUE_WEIGHTAGE_NOTIONAL
        prorata = round(target * fy_progress_val, 2)
        office_data.append({
            "office_id": oid,
            "office_name": o["office__office_name"],
            "officer_count": o["office__officer_count"] or 0,
            "target": target,
            "prorata_target": prorata,
            "assignment_count": o["assignment_count"],
            "total_revenue": rev,
            "assignment_revenue": o["sum_assignment_revenue"] or 0,
            "training_revenue": o["sum_training_revenue"] or 0,
            "notional_revenue": notional,
            "total_contribution": round(contribution, 2),
            "deposits": o["deposits"] or 0,
            "total_expenditure": o["sum_expenditure"] or 0,
            "surplus_deficit": o["sum_surplus"] or 0,
            "project_count": o["project_count"],
            "training_count": o["training_count"],
            "avg_physical_progress": round(o["avg_physical_progress"] or 0, 1),
            "achievement_pct": round((contribution / target * 100), 1) if target > 0 else 0,
            "prorata_achievement_pct": round((contribution / prorata * 100), 1) if prorata > 0 else 0,
        })

    office_data.sort(key=lambda x: x["achievement_pct"], reverse=True)

    if can_rank and len(office_data) > 3:
        for i, o in enumerate(office_data):
            o["is_top"] = i < 3
            o["is_bottom"] = i >= len(office_data) - 3

    return office_data


def _load_officer_data(qs, fy_progress_val, filter_office, can_rank):
    """Load officer-wise target vs achievement."""
    officer_shares = (
        RevenueShare.objects.filter(assignment__in=qs)
        .values("officer__officer_id", "officer__name", "officer__office_id", "officer__designation", "officer__annual_target")
        .annotate(
            assignment_count=Count("assignment", distinct=True),
            total_share_amount=Sum("share_amount"),
            avg_share_percent=Avg("share_percent"),
        )
    )

    notional_by_officer = dict(
        NonRevenueSuggestion.objects.filter(status="COMPLETED", officer__isnull=False)
        .values_list("officer__officer_id")
        .annotate(nr=Sum("notional_value"))
        .values_list("officer__officer_id", "nr")
    )

    officer_data = []
    for o in officer_shares:
        target = o["officer__annual_target"] or 60.0
        real = o["total_share_amount"] or 0
        notional = notional_by_officer.get(o["officer__officer_id"], 0) or 0
        contribution = real * settings.REVENUE_WEIGHTAGE_REAL + notional * settings.REVENUE_WEIGHTAGE_NOTIONAL
        prorata = round(target * fy_progress_val, 2)
        officer_data.append({
            "officer_id": o["officer__officer_id"],
            "name": o["officer__name"],
            "office_id": o["officer__office_id"],
            "designation": o["officer__designation"],
            "annual_target": target,
            "prorata_target": prorata,
            "assignment_count": o["assignment_count"],
            "real_revenue": round(real, 2),
            "notional_revenue": round(notional, 2),
            "total_contribution": round(contribution, 2),
            "achievement_pct": round((contribution / target * 100), 1) if target > 0 else 0,
            "prorata_achievement_pct": round((contribution / prorata * 100), 1) if prorata > 0 else 0,
        })

    officer_data.sort(key=lambda x: x["achievement_pct"], reverse=True)
    return officer_data


@login_required
def mis_dashboard(request):
    """6-tab MIS Command Center."""
    active_tab = request.GET.get("active_tab", "executive")
    if active_tab not in VALID_TABS:
        active_tab = "executive"

    financial_year = request.GET.get("financial_year") or _default_fy()
    filter_office = request.GET.get("filter_office")
    filter_domain = request.GET.get("filter_domain")
    filter_type = request.GET.get("filter_type")

    fy_prog = _fy_progress()
    can_rank = _can_see_rankings(request.user)

    qs = _build_base_qs(financial_year, filter_office, filter_domain, filter_type)

    offices = Office.objects.order_by("office_id")
    domains = list(
        Assignment.objects.filter(domain__isnull=False)
        .values_list("domain", flat=True).distinct().order_by("domain")
    )

    tab_data = {}
    office_data = []
    domain_data = []
    totals = {}

    if active_tab in ("executive", "office"):
        office_data = _load_office_data(qs, financial_year, fy_prog, can_rank)

        domain_data = list(
            qs.values("domain")
            .annotate(
                assignment_count=Count("id"),
                sum_revenue=Sum("total_revenue"),
                sum_expenditure=Sum("total_expenditure"),
                avg_physical_progress=Avg("physical_progress_percent"),
            )
            .filter(assignment_count__gt=0)
            .order_by("-sum_revenue")
        )

        total_target = sum(o["target"] for o in office_data)
        total_rev = sum(o["total_revenue"] for o in office_data)
        total_contribution = sum(o["total_contribution"] for o in office_data)
        total_exp = sum(o["sum_expenditure"] for o in office_data)
        prorata_target = round(total_target * fy_prog, 2)

        totals = {
            "total_assignments": sum(o["assignment_count"] for o in office_data),
            "total_target": total_target,
            "prorata_target": prorata_target,
            "total_revenue": total_rev,
            "total_contribution": total_contribution,
            "total_expenditure": total_exp,
            "surplus_deficit": total_rev - total_exp,
            "achievement_pct": round((total_contribution / prorata_target * 100), 1) if prorata_target > 0 else 0,
            "fy_progress_pct": round(fy_prog * 100, 1),
        }

        tab_data["office_data"] = office_data
        tab_data["domain_data"] = domain_data
        tab_data["totals"] = totals

        if active_tab == "executive":
            tab_data["officer_data"] = _load_officer_data(qs, fy_prog, filter_office, can_rank)

    elif active_tab == "activity":
        type_data = list(
            qs.values("type")
            .annotate(
                count=Count("id"),
                sum_revenue=Sum("total_revenue"),
                sum_expenditure=Sum("total_expenditure"),
                avg_progress=Avg("physical_progress_percent"),
            )
            .order_by("-sum_revenue")
        )
        tab_data["type_data"] = type_data

    elif active_tab == "financial":
        pipeline = qs.aggregate(
            gross_value=Sum("gross_value"),
            total_invoiced=Sum("invoice_amount"),
            total_received=Sum("amount_received"),
            sum_revenue=Sum("total_revenue"),
            sum_expenditure=Sum("total_expenditure"),
        )
        pipeline["net_revenue"] = (pipeline["total_received"] or 0) - (pipeline["sum_expenditure"] or 0)
        pipeline["collection_rate"] = (
            round((pipeline["total_received"] or 0) / pipeline["total_invoiced"] * 100, 1)
            if pipeline.get("total_invoiced")
            else 0
        )
        tab_data["financial"] = {"pipeline": pipeline}

    elif active_tab == "delays":
        today = date.today()
        threshold = today - timedelta(days=30)

        pd_count = InvoiceRequest.objects.filter(
            status__in=["APPROVED", "INVOICED"], payments__isnull=True,
        ).count()
        md_count = Milestone.objects.filter(
            target_date__lt=today,
        ).exclude(status__in=["Completed", "Cancelled"]).count()
        ad_count = Assignment.objects.filter(
            workflow_stage__in=["REGISTRATION", "TL_ASSIGNMENT", "DETAIL_ENTRY"],
            created_at__date__lt=threshold,
        ).count()

        tab_data["delays"] = {
            "summary": {
                "payment_count": pd_count,
                "milestone_count": md_count,
                "activation_count": ad_count,
            },
        }

    elif active_tab == "officer_client":
        tab_data["officer_data"] = _load_officer_data(qs, fy_prog, filter_office, can_rank)

        client_data = list(
            Client.objects.annotate(
                assignment_count=Count("assignment_links__assignment", distinct=True),
                total_value=Sum("assignment_links__assignment__gross_value"),
                invoiced=Sum("assignment_links__assignment__invoice_amount"),
                received=Sum("assignment_links__assignment__amount_received"),
            )
            .filter(assignment_count__gt=0)
            .order_by("-total_value")
            .values("id", "client_name", "client_type", "assignment_count", "total_value", "invoiced", "received")[:50]
        )
        tab_data["client_data"] = client_data

    return render(request, "mis/dashboard.html", {
        "active_tab": active_tab,
        "tab_data": tab_data,
        "offices": offices,
        "domains": domains,
        "financial_years": _get_financial_years(),
        "filter_office": filter_office,
        "filter_domain": filter_domain,
        "filter_type": filter_type,
        "financial_year": financial_year,
        "fy_progress": fy_prog,
        "can_see_rankings": can_rank,
        "totals": totals,
        "office_data": office_data,
        "domain_data": domain_data,
    })


@login_required
def mis_export_csv(request):
    """Export current tab data as CSV."""
    tab = request.GET.get("tab", "office")
    financial_year = request.GET.get("financial_year") or _default_fy()
    filter_office = request.GET.get("filter_office")
    filter_domain = request.GET.get("filter_domain")
    filter_type = request.GET.get("filter_type")

    fy_prog = _fy_progress()
    can_rank = _can_see_rankings(request.user)
    qs = _build_base_qs(financial_year, filter_office, filter_domain, filter_type)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f"attachment; filename=mis_{tab}_{financial_year}.csv"
    writer = csv.writer(response)

    if tab in ("executive", "office"):
        office_data = _load_office_data(qs, financial_year, fy_prog, can_rank)
        writer.writerow([
            "Office", "Target", "Pro-rata", "Assignment Rev", "Training Rev",
            "Notional", "Total", "Achievement %", "Expenditure", "Surplus",
        ])
        for o in office_data:
            writer.writerow([
                o["office_id"], o["target"], round(o["prorata_target"], 1),
                round(o["sum_assignment_revenue"], 1), round(o["sum_training_revenue"], 1),
                round(o["notional_revenue"], 1), round(o["total_contribution"], 1),
                o["achievement_pct"], round(o["sum_expenditure"], 1),
                round(o["sum_surplus"], 1),
            ])
    elif tab == "officer_client":
        officer_data = _load_officer_data(qs, fy_prog, filter_office, can_rank)
        writer.writerow([
            "Officer", "Office", "Target", "Real Revenue", "Notional",
            "Total", "Achievement %", "Assignments",
        ])
        for o in officer_data:
            writer.writerow([
                o["name"], o["office_id"], o["annual_target"],
                round(o["real_revenue"], 1), round(o["notional_revenue"], 1),
                round(o["total_contribution"], 1), o["achievement_pct"],
                o["assignment_count"],
            ])
    else:
        writer.writerow(["No data for this tab"])

    return response


@login_required
def office_detail(request, office_id):
    """Detailed view for a specific office."""
    office = Office.objects.filter(office_id=office_id).first()
    if not office:
        return redirect("core:mis_dashboard")

    fy_prog = _fy_progress()
    financial_year = _default_fy()

    assignments = Assignment.objects.filter(office=office).order_by("-start_date")

    # Officer data for this office
    officer_shares = (
        RevenueShare.objects.filter(assignment__office=office)
        .values("officer__officer_id", "officer__name", "officer__annual_target")
        .annotate(
            assignment_count=Count("assignment", distinct=True),
            total_share=Sum("share_amount"),
        )
        .order_by("-total_share")
    )

    # FY target
    try:
        fy_target = FinancialYearTarget.objects.get(
            office=office, financial_year=financial_year,
        )
    except FinancialYearTarget.DoesNotExist:
        fy_target = None

    target = fy_target.annual_target if fy_target else office.annual_revenue_target
    prorata = round(target * fy_prog, 2)
    total_rev = sum(a.total_revenue or 0 for a in assignments)

    return render(request, "mis/office_detail.html", {
        "office": office,
        "assignments": assignments,
        "officer_shares": officer_shares,
        "target": target,
        "prorata_target": prorata,
        "total_revenue": total_rev,
        "achievement_pct": round((total_rev / target * 100), 1) if target > 0 else 0,
        "fy_target": fy_target,
        "financial_year": financial_year,
    })
