"""
MIS V2 — three simpler dashboards (SCOPE_V2 §3.8).

Replaces the retired 6-tab Command Center with:
  1. Pre-WO MIS    — conversion funnel + drop-off
  2. Revenue MIS   — assignments + training 80-20, officer/office rollups
  3. Non-Revenue MIS — man-days by officer / office / category

Access matrix (§10):
  DG / DDG / ADMIN -> organization-wide
  GH / RD          -> own office only
  Officer / TL     -> self only
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render

from core.models import (
    ExpenditureItem, MacroExpenseCategory, NonRevenueSuggestion,
    OfficerRevenueLedger, PreWORecord, TrainingExpenseItem,
    TrainingRevenueLedger,
)


ORG_ROLES = {"ADMIN", "DG", "DDG-I", "DDG-II"}
HEAD_ROLES = {"RD_HEAD", "GROUP_HEAD"}


def _scope(user):
    """Return (level, office_id, officer_id). level: 'ORG' | 'OFFICE' | 'SELF'."""
    role = (user.admin_role_id or "").upper()
    if role in ORG_ROLES:
        return ("ORG", None, user.officer_id)
    if role in HEAD_ROLES:
        return ("OFFICE", getattr(user.office, "office_id", None), user.officer_id)
    return ("SELF", getattr(user.office, "office_id", None), user.officer_id)


def _scope_label(level, office_id):
    return {
        "ORG": "Organization-wide",
        "OFFICE": f"Office: {office_id}",
        "SELF": "My records only",
    }[level]


# ------------------------------------------------------------------
# 1. Pre-WO MIS
# ------------------------------------------------------------------

@login_required
def pre_wo_mis(request):
    level, office_id, officer_id = _scope(request.user)
    qs = PreWORecord.objects.all()
    if level == "OFFICE":
        qs = qs.filter(office__office_id=office_id)
    elif level == "SELF":
        qs = qs.filter(created_by_id=officer_id)

    total = qs.count()
    converted = qs.filter(outcome="CONVERTED_TO_WO").count()
    conversion_rate = round((converted / total * 100), 1) if total else 0.0

    by_office = list(
        qs.values("office__office_id", "office__office_name")
        .annotate(count=Count("id"), converted=Count("id", filter=Q(outcome="CONVERTED_TO_WO")))
        .order_by("-count")[:12]
    )

    return render(request, "mis/pre_wo_mis.html", {
        "scope_label": _scope_label(level, office_id),
        "kpis": {
            "total": total,
            "enquiry": qs.filter(stage="ENQUIRY").count(),
            "prelim": qs.filter(stage="PRELIM_VISIT").count(),
            "proposal": qs.filter(stage="PROPOSAL").count(),
            "converted": converted,
            "dropped": qs.filter(outcome="DROPPED").count(),
            "on_hold": qs.filter(outcome="ON_HOLD").count(),
            "conversion_rate": conversion_rate,
        },
        "by_office": by_office,
    })


# ------------------------------------------------------------------
# 2. Revenue MIS (assignments + training, 80-20)
# ------------------------------------------------------------------

@login_required
def revenue_mis(request):
    level, office_id, officer_id = _scope(request.user)

    asg_ledger = OfficerRevenueLedger.objects.all()
    trn_ledger = TrainingRevenueLedger.objects.all()
    if level == "OFFICE":
        asg_ledger = asg_ledger.filter(assignment__office__office_id=office_id)
        trn_ledger = trn_ledger.filter(programme__office__office_id=office_id)
    elif level == "SELF":
        asg_ledger = asg_ledger.filter(officer_id=officer_id)
        trn_ledger = trn_ledger.filter(officer_id=officer_id)

    asg_total = asg_ledger.aggregate(s=Sum("amount"))["s"] or 0
    trn_total = trn_ledger.aggregate(s=Sum("amount"))["s"] or 0
    asg_80 = asg_ledger.filter(revenue_type="INVOICE_80").aggregate(s=Sum("amount"))["s"] or 0
    asg_20 = asg_ledger.filter(revenue_type="PAYMENT_20").aggregate(s=Sum("amount"))["s"] or 0
    trn_80 = trn_ledger.filter(revenue_type="COMPLETION_80").aggregate(s=Sum("amount"))["s"] or 0
    trn_20 = trn_ledger.filter(revenue_type="PAYMENT_20").aggregate(s=Sum("amount"))["s"] or 0

    officer_map = {}
    for row in asg_ledger.values("officer_id", "officer__name").annotate(s=Sum("amount")):
        officer_map.setdefault(row["officer_id"], {"name": row["officer__name"], "amount": 0})
        officer_map[row["officer_id"]]["amount"] += row["s"] or 0
    for row in trn_ledger.values("officer_id", "officer__name").annotate(s=Sum("amount")):
        officer_map.setdefault(row["officer_id"], {"name": row["officer__name"], "amount": 0})
        officer_map[row["officer_id"]]["amount"] += row["s"] or 0
    by_officer = sorted(officer_map.values(), key=lambda r: r["amount"], reverse=True)[:12]

    # ---- Combined expenditure rollup by shared macro-category ----
    # Unions consultancy (ExpenditureItem) + training (TrainingExpenseItem) so
    # the two independent streams roll up into common buckets. Office-scoped;
    # not shown at SELF level (officers don't own programme/assignment costs).
    asg_items = ExpenditureItem.objects.all()
    trn_items = TrainingExpenseItem.objects.all()
    if level == "OFFICE":
        asg_items = asg_items.filter(assignment__office__office_id=office_id)
        trn_items = trn_items.filter(programme__office__office_id=office_id)

    macro_labels = dict(MacroExpenseCategory.choices)
    macro_rows = {k: {"label": v, "consultancy": 0.0, "training": 0.0}
                  for k, v in MacroExpenseCategory.choices}
    if level != "SELF":
        for row in (asg_items.values("head__macro_category")
                    .annotate(s=Sum("actual_amount"))):
            mc = row["head__macro_category"] or "MISC"
            macro_rows.setdefault(mc, {"label": macro_labels.get(mc, mc), "consultancy": 0.0, "training": 0.0})
            macro_rows[mc]["consultancy"] += row["s"] or 0
        for row in (trn_items.values("head__macro_category")
                    .annotate(s=Sum("actual_amount"))):
            mc = row["head__macro_category"] or "MISC"
            macro_rows.setdefault(mc, {"label": macro_labels.get(mc, mc), "consultancy": 0.0, "training": 0.0})
            macro_rows[mc]["training"] += row["s"] or 0

    expense_rows = []
    exp_consultancy = exp_training = 0.0
    for mc, r in macro_rows.items():
        total = r["consultancy"] + r["training"]
        exp_consultancy += r["consultancy"]
        exp_training += r["training"]
        if total > 0:
            expense_rows.append({"label": r["label"], "consultancy": r["consultancy"],
                                 "training": r["training"], "total": total})
    expense_rows.sort(key=lambda x: x["total"], reverse=True)

    return render(request, "mis/revenue_mis.html", {
        "scope_label": _scope_label(level, office_id),
        "kpis": {
            "total": asg_total + trn_total,
            "assignment_total": asg_total,
            "training_total": trn_total,
            "recognized_80": asg_80 + trn_80,
            "recognized_20": asg_20 + trn_20,
        },
        "by_officer": by_officer,
        "expense_rows": expense_rows,
        "exp_consultancy": exp_consultancy,
        "exp_training": exp_training,
        "exp_total": exp_consultancy + exp_training,
        "show_expenses": level != "SELF",
    })


# ------------------------------------------------------------------
# 3. Non-Revenue MIS (man-days)
# ------------------------------------------------------------------

@login_required
def non_revenue_mis(request):
    level, office_id, officer_id = _scope(request.user)
    qs = NonRevenueSuggestion.objects.all()
    if level == "OFFICE":
        qs = qs.filter(office__office_id=office_id)
    elif level == "SELF":
        qs = qs.filter(officer_id=officer_id)

    by_officer = list(
        qs.exclude(officer__isnull=True)
        .values("officer_id", "officer__name")
        .annotate(man_days=Sum("man_days"), tasks=Count("id"))
        .order_by("-man_days")[:12]
    )
    by_category = list(
        qs.values("activity_type")
        .annotate(man_days=Sum("man_days"), tasks=Count("id"))
        .order_by("-man_days")
    )

    return render(request, "mis/non_revenue_mis.html", {
        "scope_label": _scope_label(level, office_id),
        "kpis": {
            "total_tasks": qs.count(),
            "total_man_days": qs.aggregate(s=Sum("man_days"))["s"] or 0,
            "completed": qs.filter(status="COMPLETED").count(),
            "in_progress": qs.filter(status="IN_PROGRESS").count(),
        },
        "by_officer": by_officer,
        "by_category": by_category,
    })
