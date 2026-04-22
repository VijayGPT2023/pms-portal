"""
Dashboard views: 4-tab MIS dashboard with role-based views.
Ported from FastAPI dashboard_routes.py to Django ORM.

Tabs: Default MIS, Physical Progress, Financial Progress, Business MIS.
Role hierarchy: DG > DDG > RD_HEAD/GROUP_HEAD > TEAM_LEADER > OFFICER.
"""
from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum, Count, Avg, Q, F, Case, When, Value, FloatField, IntegerField,
    Subquery, OuterRef, CharField,
)
from django.db.models.functions import Coalesce, ExtractMonth
from django.http import JsonResponse
from django.shortcuts import render

from core.models import (
    Assignment, Officer, Office, OfficerRole, ReportingHierarchy,
    Milestone, RevenueShare, InvoiceRequest, PaymentReceipt,
    ExpenditureEntry, NonRevenueSuggestion, FinancialYearTarget,
)


# =========================================================================
# Utility helpers
# =========================================================================

VALID_TABS = ('default_mis', 'physical_progress', 'financial_progress', 'business_mis')
TAB_MIGRATION = {
    'assignments': 'default_mis',
    'training': 'default_mis',
    'total_real_revenue': 'default_mis',
    'total_revenue': 'default_mis',
    'development': 'default_mis',
}


def _get_current_fy():
    """Return the current financial year string, e.g. '2025-26'."""
    today = date.today()
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[-2:]}"
    return f"{today.year - 1}-{str(today.year)[-2:]}"


def _calculate_fy_progress():
    """Calculate how much of the financial year has elapsed (0.0-1.0)."""
    today = date.today()
    if today.month >= 4:
        fy_start = date(today.year, 4, 1)
    else:
        fy_start = date(today.year - 1, 4, 1)
    fy_end = date(fy_start.year + 1, 3, 31)
    total_days = (fy_end - fy_start).days
    elapsed_days = (today - fy_start).days
    return min(elapsed_days / total_days, 1.0)


def _get_fy_date_range(fy: str):
    """Convert FY string (e.g. '2025-26') to (start_date, end_date)."""
    parts = fy.split('-')
    start_year = int(parts[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def _get_available_fys():
    """Get list of available financial years from data."""
    current_fy = _get_current_fy()
    fys = {current_fy}
    for fy in InvoiceRequest.objects.filter(
        fy_period__isnull=False
    ).values_list('fy_period', flat=True).distinct():
        if fy:
            fys.add(fy)
    for fy in FinancialYearTarget.objects.filter(
        financial_year__isnull=False
    ).values_list('financial_year', flat=True).distinct():
        if fy:
            fys.add(fy)
    return sorted(fys, reverse=True)


def _get_active_role_info(user):
    """Get the user's active role, scope_type, scope_value."""
    if not user or not user.is_authenticated:
        return 'OFFICER', None, None

    active_role = getattr(user, '_active_role', None)
    if not active_role:
        # Determine from OfficerRole or admin_role_id
        if user.admin_role_id in ('ADMIN', 'DG', 'DDG-I', 'DDG-II'):
            active_role = user.admin_role_id
        else:
            role = OfficerRole.objects.filter(
                officer=user.officer_id
            ).order_by('-is_primary', '-created_at').first()
            if role:
                active_role = role.role_type
            else:
                active_role = 'OFFICER'

    # Find scope from OfficerRole
    role_obj = OfficerRole.objects.filter(
        officer=user.officer_id,
        role_type=active_role,
    ).first()
    scope_type = role_obj.scope_type if role_obj else None
    scope_value = role_obj.scope_value if role_obj else None

    return active_role, scope_type, scope_value


def _get_offices_for_ddg(ddg_role: str):
    """Get list of office_ids that report to a DDG role."""
    return list(
        ReportingHierarchy.objects.filter(
            entity_type='OFFICE', reports_to_role=ddg_role
        ).values_list('entity_value', flat=True)
    )


def _get_groups_for_ddg(ddg_role: str):
    """Get list of group codes that report to a DDG role."""
    return list(
        ReportingHierarchy.objects.filter(
            entity_type='GROUP', reports_to_role=ddg_role
        ).values_list('entity_value', flat=True)
    )


def _build_role_filter(active_role, scope_value, user, role_offices, role_groups):
    """Build assignment queryset filter, view_title, and view_type.

    Returns (filter_kwargs_or_Q, view_title, view_type, is_individual).
    For individual officers, returns a special marker.
    """
    if active_role == 'DG':
        return Q(), "Director General View", "npc", False
    elif active_role in ('DDG-I', 'DDG-II'):
        all_ids = role_offices + role_groups
        if all_ids:
            return Q(office_id__in=all_ids), f"{active_role} View", "ddg", False
        return Q(pk__isnull=True), f"{active_role} View", "ddg", False  # match nothing
    elif active_role == 'GROUP_HEAD' and scope_value:
        return Q(office_id=scope_value), f"Group Head ({scope_value}) View", "group", False
    elif active_role == 'RD_HEAD' and scope_value:
        return Q(office_id=scope_value), f"RD Head ({scope_value}) View", "office", False
    elif active_role == 'TEAM_LEADER':
        return Q(team_leader=user.officer_id), "Team Leader View", "team_leader", False
    elif active_role == 'ADMIN':
        return Q(), "Administrator View", "npc", False
    else:
        # OFFICER (Individual)
        return Q(), "My Dashboard", "individual", True


def _get_office_ids_for_role(active_role, scope_value, user, role_offices, role_groups):
    """Return the list of office_ids visible to the user's role."""
    if active_role in ('DG', 'ADMIN'):
        return list(Office.objects.values_list('office_id', flat=True).order_by('office_id'))
    elif active_role in ('DDG-I', 'DDG-II'):
        return role_offices + role_groups
    elif active_role in ('GROUP_HEAD', 'RD_HEAD'):
        return [scope_value] if scope_value else []
    else:
        return [user.office_id_value] if hasattr(user, 'office_id_value') and user.office_id_value else []


def _traffic_light(days):
    """Return traffic light color based on delay days."""
    if days is None or days < 30:
        return 'green'
    elif days < 60:
        return 'amber'
    return 'red'


# =========================================================================
# Tab A: Default MIS
# =========================================================================

def _get_default_mis_data(active_role, scope_value, user, fy, role_offices, role_groups):
    """Tab A: Office-proportionate Target-Revenue-Expenditure-Surplus."""
    fy_start, fy_end = _get_fy_date_range(fy)
    office_ids = _get_office_ids_for_role(active_role, scope_value, user, role_offices, role_groups)

    if not office_ids:
        return {
            'summary': {'fy_target': 0, 'revenue': 0, 'expenditure': 0, 'surplus_deficit': 0},
            'office_rows': [],
        }

    # FY targets by office
    targets = dict(
        FinancialYearTarget.objects.filter(
            office_id__in=office_ids, financial_year=fy
        ).values_list('office_id', 'annual_target')
    )

    # Billed by office (invoice_amount for invoices in the FY)
    billed = dict(
        InvoiceRequest.objects.filter(
            assignment__office_id__in=office_ids, fy_period=fy
        ).values('assignment__office_id').annotate(
            total=Coalesce(Sum('invoice_amount'), 0.0)
        ).values_list('assignment__office_id', 'total')
    )

    # Payment received by office
    received = dict(
        PaymentReceipt.objects.filter(
            invoice_request__assignment__office_id__in=office_ids,
            fy_period=fy
        ).values('invoice_request__assignment__office_id').annotate(
            total=Coalesce(Sum('amount_received'), 0.0)
        ).values_list('invoice_request__assignment__office_id', 'total')
    )

    # Expenditure by office
    expenses = dict(
        ExpenditureEntry.objects.filter(
            assignment__office_id__in=office_ids, fy_period=fy
        ).values('assignment__office_id').annotate(
            total=Coalesce(Sum('amount'), 0.0)
        ).values_list('assignment__office_id', 'total')
    )

    # Build office rows
    offices = Office.objects.filter(office_id__in=office_ids).order_by('office_id')
    fy_progress = _calculate_fy_progress()
    office_rows = []
    for o in offices:
        oid = o.office_id
        target = targets.get(oid, 0) or 0
        rev = billed.get(oid, 0) or 0
        pay = received.get(oid, 0) or 0
        exp = expenses.get(oid, 0) or 0
        row = {
            'office_id': oid,
            'office_name': o.office_name,
            'fy_target': target,
            'revenue': rev,
            'payment_received': pay,
            'expenditure': exp,
            'surplus_deficit': pay - exp,
            'prorata_target': round(target * fy_progress, 2),
            'achievement_pct': round(rev / target * 100, 1) if target > 0 else 0,
        }
        office_rows.append(row)

    # Sort by target desc
    office_rows.sort(key=lambda r: r['fy_target'], reverse=True)

    summary = {
        'fy_target': sum(r['fy_target'] for r in office_rows),
        'revenue': sum(r['revenue'] for r in office_rows),
        'expenditure': sum(r['expenditure'] for r in office_rows),
        'surplus_deficit': sum(r['surplus_deficit'] for r in office_rows),
    }

    return {'summary': summary, 'office_rows': office_rows}


# =========================================================================
# Tab A Drill-down: Team Leader rows, Officer rows
# =========================================================================

def _get_tl_rows(office_id, fy):
    """Return one row per team leader for a given office with financial metrics."""
    fy_start, fy_end = _get_fy_date_range(fy)

    # Get assignments for this office
    assignments = Assignment.objects.filter(office_id=office_id)

    # Aggregate by TL
    tl_stats = assignments.values(
        'team_leader'
    ).annotate(
        active_count=Count('id', filter=Q(status__in=['In Progress', 'Not Started', 'Ongoing'])),
        targeted_value=Coalesce(Sum('gross_value'), 0.0),
    ).order_by('-targeted_value')

    # Billed by TL
    billed_by_tl = dict(
        InvoiceRequest.objects.filter(
            assignment__office_id=office_id, fy_period=fy
        ).values('assignment__team_leader').annotate(
            total=Coalesce(Sum('invoice_amount'), 0.0)
        ).values_list('assignment__team_leader', 'total')
    )

    # Received by TL
    received_by_tl = dict(
        PaymentReceipt.objects.filter(
            invoice_request__assignment__office_id=office_id,
            fy_period=fy
        ).values('invoice_request__assignment__team_leader').annotate(
            total=Coalesce(Sum('amount_received'), 0.0)
        ).values_list('invoice_request__assignment__team_leader', 'total')
    )

    # Expenses by TL
    expenses_by_tl = dict(
        ExpenditureEntry.objects.filter(
            assignment__office_id=office_id, fy_period=fy
        ).values('assignment__team_leader').annotate(
            total=Coalesce(Sum('amount'), 0.0)
        ).values_list('assignment__team_leader', 'total')
    )

    # Build rows
    rows = []
    for stat in tl_stats:
        tl_id = stat['team_leader']
        if tl_id is None:
            # Count unassigned
            active_cnt = stat['active_count'] or 0
            if active_cnt > 0:
                rows.append({
                    'officer_id': '__unassigned__',
                    'tl_name': 'Unassigned (No TL)',
                    'designation': '-',
                    'active_count': active_cnt,
                    'targeted_value': stat['targeted_value'] or 0,
                    'tentative_value': 0,
                    'completed_value': 0,
                    'billed_fy': 0,
                    'to_be_billed': 0,
                    'payment_received': 0,
                    'expenses_fy': 0,
                    'net_value': 0,
                    'surplus_deficit': 0,
                })
            continue

        # Look up officer info
        try:
            officer = Officer.objects.get(officer_id=tl_id)
            tl_name = officer.name
            designation = officer.designation or '-'
        except Officer.DoesNotExist:
            tl_name = tl_id
            designation = '-'

        b = billed_by_tl.get(tl_id, 0) or 0
        r = received_by_tl.get(tl_id, 0) or 0
        e = expenses_by_tl.get(tl_id, 0) or 0

        rows.append({
            'officer_id': tl_id,
            'tl_name': tl_name,
            'designation': designation,
            'active_count': stat['active_count'] or 0,
            'targeted_value': stat['targeted_value'] or 0,
            'tentative_value': stat['targeted_value'] or 0,
            'completed_value': 0,
            'billed_fy': b,
            'to_be_billed': max((stat['targeted_value'] or 0) - b, 0),
            'payment_received': r,
            'expenses_fy': e,
            'net_value': (stat['targeted_value'] or 0) - e,
            'surplus_deficit': r - e,
        })

    return rows


def _get_officer_rows(tl_officer_id, fy):
    """Return one row per officer for a given TL with revenue metrics."""
    fy_start, fy_end = _get_fy_date_range(fy)

    # Get assignments led by this TL
    tl_assignments = Assignment.objects.filter(team_leader=tl_officer_id)
    tl_assignment_ids = list(tl_assignments.values_list('id', flat=True))

    if not tl_assignment_ids:
        return []

    # All officers with revenue shares on these assignments
    officer_stats = RevenueShare.objects.filter(
        assignment_id__in=tl_assignment_ids
    ).values('officer_id').annotate(
        targeted_value=Coalesce(
            Sum(F('assignment__gross_value') * F('share_percent') / 100.0),
            0.0, output_field=FloatField()
        ),
    ).order_by('-targeted_value')

    rows = []
    for stat in officer_stats:
        oid = stat['officer_id']
        try:
            officer = Officer.objects.get(officer_id=oid)
        except Officer.DoesNotExist:
            continue

        targeted = stat['targeted_value'] or 0

        # Completed value: milestones completed * gross_value * revenue_percent * share_percent
        completed = RevenueShare.objects.filter(
            officer_id=oid,
            assignment_id__in=tl_assignment_ids,
            assignment__milestones__status='Completed',
            assignment__milestones__actual_completion_date__gte=fy_start,
            assignment__milestones__actual_completion_date__lte=fy_end,
        ).aggregate(
            total=Coalesce(
                Sum(
                    F('assignment__gross_value') *
                    F('assignment__milestones__revenue_percent') / 100.0 *
                    F('share_percent') / 100.0
                ),
                0.0, output_field=FloatField()
            )
        )['total']

        rows.append({
            'officer_id': oid,
            'name': officer.name,
            'designation': officer.designation or '-',
            'officer_office': officer.office_id_value,
            'annual_target': officer.annual_target or 60.0,
            'targeted_value': targeted,
            'tentative_value': targeted,
            'completed_value': completed or 0,
            'revenue_earned': completed or 0,
        })

    return rows


def _get_items_for_officer(officer_id, filter_status=None):
    """Return assignment items for an individual officer (via revenue shares)."""
    qs = Assignment.objects.filter(
        revenue_shares__officer_id=officer_id
    ).distinct().values(
        'id', 'assignment_no', 'type', 'title', 'client', 'office_id',
        'status', 'gross_value', 'invoice_amount', 'amount_received',
        'total_revenue', 'details_filled', 'total_expenditure',
        'surplus_deficit', 'target_date', 'start_date',
    )
    if filter_status:
        qs = qs.filter(status=filter_status)
    return list(qs.order_by('-assignment_no')[:100])


def _build_breadcrumbs(sub_view, sub_id, active_tab, fy, active_role, scope_value):
    """Build breadcrumb trail for hierarchical navigation."""
    base_url = f"/dashboard/?active_tab={active_tab}&fy={fy}"
    crumbs = []

    if active_role in ('DG', 'DDG-I', 'DDG-II', 'ADMIN'):
        crumbs.append({'label': 'All Offices', 'url': base_url})

        if sub_view in ('team_leaders', 'officers', 'items') and sub_id:
            if sub_view == 'team_leaders':
                try:
                    office = Office.objects.get(office_id=sub_id)
                    label = office.office_name
                except Office.DoesNotExist:
                    label = sub_id
                crumbs.append({'label': label, 'url': f"{base_url}&sub_view=team_leaders&sub_id={sub_id}"})

            elif sub_view == 'officers':
                try:
                    officer = Officer.objects.get(officer_id=sub_id)
                    tl_name = officer.name
                    tl_office = officer.office_id_value
                    try:
                        office = Office.objects.get(office_id=tl_office)
                        office_label = office.office_name
                    except Office.DoesNotExist:
                        office_label = tl_office
                    crumbs.append({'label': office_label, 'url': f"{base_url}&sub_view=team_leaders&sub_id={tl_office}"})
                    crumbs.append({'label': f"TL: {tl_name}", 'url': f"{base_url}&sub_view=officers&sub_id={sub_id}"})
                except Officer.DoesNotExist:
                    pass

            elif sub_view == 'items':
                try:
                    officer = Officer.objects.get(officer_id=sub_id)
                    off_name = officer.name
                    off_office = officer.office_id_value
                    try:
                        office = Office.objects.get(office_id=off_office)
                        office_label = office.office_name
                    except Office.DoesNotExist:
                        office_label = off_office
                    crumbs.append({'label': office_label, 'url': f"{base_url}&sub_view=team_leaders&sub_id={off_office}"})
                    crumbs.append({'label': off_name, 'url': f"{base_url}&sub_view=items&sub_id={sub_id}"})
                except Officer.DoesNotExist:
                    pass

    elif active_role in ('GROUP_HEAD', 'RD_HEAD'):
        label = f"{'Group' if active_role == 'GROUP_HEAD' else 'Office'}: {scope_value}"
        crumbs.append({'label': label, 'url': base_url})

        if sub_view == 'officers' and sub_id:
            try:
                tl = Officer.objects.get(officer_id=sub_id)
                crumbs.append({'label': f"TL: {tl.name}", 'url': f"{base_url}&sub_view=officers&sub_id={sub_id}"})
            except Officer.DoesNotExist:
                pass
        elif sub_view == 'items' and sub_id:
            try:
                off = Officer.objects.get(officer_id=sub_id)
                crumbs.append({'label': off.name, 'url': f"{base_url}&sub_view=items&sub_id={sub_id}"})
            except Officer.DoesNotExist:
                pass

    elif active_role == 'TEAM_LEADER':
        crumbs.append({'label': 'My Team', 'url': base_url})
        if sub_view == 'items' and sub_id:
            try:
                off = Officer.objects.get(officer_id=sub_id)
                crumbs.append({'label': off.name, 'url': f"{base_url}&sub_view=items&sub_id={sub_id}"})
            except Officer.DoesNotExist:
                pass

    return crumbs


# =========================================================================
# Tab B: Physical Progress
# =========================================================================

def _get_physical_progress_data(role_q, is_individual, user, fy, filter_office=None):
    """Tab B: Milestone delay analysis with traffic-light indicators."""
    fy_start, fy_end = _get_fy_date_range(fy)
    today = date.today()

    # Base queryset for milestones in scope
    ms_qs = Milestone.objects.filter(
        assignment__in=_get_scoped_assignments(role_q, is_individual, user)
    ).exclude(status='Cancelled').filter(
        target_date__gte=fy_start, target_date__lte=fy_end
    )

    if filter_office:
        ms_qs = ms_qs.filter(assignment__office_id=filter_office)

    total = ms_qs.count()
    on_time = ms_qs.filter(
        Q(status='Completed') & (
            Q(actual_completion_date__lte=F('target_date')) |
            Q(actual_completion_date__isnull=True)
        )
    ).count()
    delayed = ms_qs.filter(
        target_date__lt=today
    ).exclude(status__in=['Completed', 'Cancelled']).count()
    upcoming = ms_qs.filter(
        target_date__gte=today
    ).exclude(status__in=['Completed', 'Cancelled']).count()

    # Average delay for delayed milestones
    delayed_ms = ms_qs.filter(
        target_date__lt=today
    ).exclude(status__in=['Completed', 'Cancelled'])

    avg_delay = 0
    if delayed > 0:
        total_delay = sum(
            (today - m.target_date).days
            for m in delayed_ms.only('target_date')
        )
        avg_delay = round(total_delay / delayed)

    # Delay distribution
    delay_distribution = {'0_30': 0, '30_60': 0, '60_90': 0, '90_plus': 0}
    for m in delayed_ms.only('target_date'):
        d = (today - m.target_date).days
        if d <= 30:
            delay_distribution['0_30'] += 1
        elif d <= 60:
            delay_distribution['30_60'] += 1
        elif d <= 90:
            delay_distribution['60_90'] += 1
        else:
            delay_distribution['90_plus'] += 1

    summary = {
        'total': total,
        'on_time': on_time,
        'delayed': delayed,
        'upcoming': upcoming,
        'avg_delay': avg_delay,
    }

    # Detailed milestone rows (delayed, limited to 100)
    milestone_rows = []
    for m in delayed_ms.select_related('assignment').order_by('target_date')[:100]:
        delay_days = (today - m.target_date).days
        milestone_rows.append({
            'id': m.id,
            'milestone_no': m.milestone_no,
            'milestone_title': m.title,
            'target_date': m.target_date,
            'status': m.status,
            'revenue_percent': m.revenue_percent,
            'assignment_no': m.assignment.assignment_no,
            'title': m.assignment.title,
            'office_id': m.assignment.office_id,
            'assignment_id': m.assignment_id,
            'delay_days': delay_days,
            'traffic_light': _traffic_light(delay_days),
        })

    # Sort by delay_days descending
    milestone_rows.sort(key=lambda r: r['delay_days'], reverse=True)

    return {
        'summary': summary,
        'milestone_rows': milestone_rows,
        'delay_distribution': delay_distribution,
    }


def _get_scoped_assignments(role_q, is_individual, user):
    """Return an Assignment queryset scoped to the user's role."""
    if is_individual:
        return Assignment.objects.filter(
            id__in=RevenueShare.objects.filter(
                officer_id=user.officer_id
            ).values_list('assignment_id', flat=True)
        )
    return Assignment.objects.filter(role_q)


# =========================================================================
# Tab C: Financial Progress
# =========================================================================

def _get_financial_progress_data(role_q, is_individual, user, fy, filter_office=None):
    """Tab C: Invoice and payment delay analysis with aging buckets."""
    fy_start, fy_end = _get_fy_date_range(fy)
    today = date.today()

    scoped_assignments = _get_scoped_assignments(role_q, is_individual, user)
    if filter_office:
        scoped_assignments = scoped_assignments.filter(office_id=filter_office)
    assignment_ids = list(scoped_assignments.values_list('id', flat=True))

    # Invoice delays: milestones past target_date but invoice not raised
    invoice_delay_ms = Milestone.objects.filter(
        assignment_id__in=assignment_ids,
        target_date__lt=today,
        target_date__gte=fy_start,
        target_date__lte=fy_end,
        invoice_raised=False,
    ).exclude(status='Cancelled').select_related('assignment').order_by('target_date')[:100]

    invoice_delays = []
    for m in invoice_delay_ms:
        delay_days = (today - m.target_date).days
        invoice_delays.append({
            'id': m.id,
            'milestone_no': m.milestone_no,
            'milestone_title': m.title,
            'target_date': m.target_date,
            'revenue_percent': m.revenue_percent,
            'assignment_no': m.assignment.assignment_no,
            'title': m.assignment.title,
            'office_id': m.assignment.office_id,
            'assignment_id': m.assignment_id,
            'delay_days': delay_days,
        })
    invoice_delays.sort(key=lambda r: r['delay_days'], reverse=True)

    # Payment delays: invoices approved but no payment received
    payment_delay_qs = InvoiceRequest.objects.filter(
        assignment_id__in=assignment_ids,
        status__in=['APPROVED', 'INVOICED'],
        approved_at__isnull=False,
        fy_period=fy,
    ).exclude(
        payments__isnull=False
    ).select_related('assignment').order_by('approved_at')[:100]

    payment_delays = []
    for ir in payment_delay_qs:
        # Check if any payment exists
        if ir.payments.exists():
            continue
        delay_days = (today - ir.approved_at.date()).days if ir.approved_at else 0
        payment_delays.append({
            'id': ir.id,
            'request_number': ir.request_number,
            'invoice_amount': ir.invoice_amount,
            'status': ir.status,
            'approved_at': ir.approved_at,
            'assignment_no': ir.assignment.assignment_no,
            'title': ir.assignment.title,
            'office_id': ir.assignment.office_id,
            'assignment_id': ir.assignment_id,
            'delay_days': delay_days,
        })
    payment_delays.sort(key=lambda r: r['delay_days'], reverse=True)

    # Summary stats
    avg_inv_delay = round(
        sum(r['delay_days'] for r in invoice_delays) / len(invoice_delays)
    ) if invoice_delays else 0
    avg_pay_delay = round(
        sum(r['delay_days'] for r in payment_delays) / len(payment_delays)
    ) if payment_delays else 0

    summary = {
        'avg_invoice_delay': avg_inv_delay,
        'avg_payment_delay': avg_pay_delay,
        'outstanding_invoices_count': len(invoice_delays),
        'outstanding_invoices_amount': sum(r.get('revenue_percent', 0) or 0 for r in invoice_delays),
        'outstanding_payments_count': len(payment_delays),
        'outstanding_payments_amount': sum(r.get('invoice_amount', 0) or 0 for r in payment_delays),
    }

    # Aging buckets
    invoice_aging = {'0_30': 0, '30_60': 0, '60_90': 0, '90_plus': 0}
    for r in invoice_delays:
        d = r.get('delay_days', 0) or 0
        if d <= 30:
            invoice_aging['0_30'] += 1
        elif d <= 60:
            invoice_aging['30_60'] += 1
        elif d <= 90:
            invoice_aging['60_90'] += 1
        else:
            invoice_aging['90_plus'] += 1

    payment_aging = {'0_30': 0, '30_60': 0, '60_90': 0, '90_plus': 0}
    for r in payment_delays:
        d = r.get('delay_days', 0) or 0
        if d <= 30:
            payment_aging['0_30'] += 1
        elif d <= 60:
            payment_aging['30_60'] += 1
        elif d <= 90:
            payment_aging['60_90'] += 1
        else:
            payment_aging['90_plus'] += 1

    return {
        'summary': summary,
        'invoice_delays': invoice_delays,
        'payment_delays': payment_delays,
        'invoice_aging': invoice_aging,
        'payment_aging': payment_aging,
    }


# =========================================================================
# Tab D: Business MIS
# =========================================================================

def _get_business_mis_data(role_q, is_individual, user, fy,
                           sub_section='proposals', filter_office=None,
                           filter_status=None, filter_domain=None,
                           sort_by=None, sort_order='desc'):
    """Tab D: Proposals pipeline + Work in Hand."""
    today = date.today()
    qs = _get_scoped_assignments(role_q, is_individual, user)

    if filter_office:
        qs = qs.filter(office_id=filter_office)
    if filter_domain:
        qs = qs.filter(domain=filter_domain)

    if sub_section == 'proposals':
        if filter_status:
            qs = qs.filter(workflow_stage=filter_status)

        # Pipeline by workflow_stage
        pipeline_raw = qs.values('workflow_stage').annotate(
            cnt=Count('id'),
            total_value=Coalesce(Sum('gross_value'), 0.0),
        ).order_by('-cnt')

        pipeline = {}
        for p in pipeline_raw:
            stage = p['workflow_stage'] or 'UNKNOWN'
            pipeline[stage] = {'cnt': p['cnt'], 'total_value': p['total_value']}

        total_proposals = sum(p['cnt'] for p in pipeline.values())
        total_pipeline_value = sum(p['total_value'] for p in pipeline.values())
        won_count = pipeline.get('ACTIVE', {}).get('cnt', 0) + pipeline.get('COMPLETED', {}).get('cnt', 0)
        won_value = pipeline.get('ACTIVE', {}).get('total_value', 0) + pipeline.get('COMPLETED', {}).get('total_value', 0)
        conversion_rate = round(won_count / total_proposals * 100, 1) if total_proposals > 0 else 0

        summary = {
            'pipeline_value': total_pipeline_value,
            'active_proposals': total_proposals,
            'won_value': won_value,
            'conversion_rate': conversion_rate,
        }

        # Sortable results
        valid_sorts = {
            'assignment_no': 'assignment_no',
            'title': 'title',
            'gross_value': 'gross_value',
            'office_id': 'office_id',
            'workflow_stage': 'workflow_stage',
        }
        order_col = valid_sorts.get(sort_by, 'created_at')
        if sort_order != 'asc':
            order_col = f'-{order_col}'

        rows = list(qs.values(
            'id', 'assignment_no', 'title', 'office_id', 'client',
            'gross_value', 'workflow_stage', 'domain', 'status',
            'team_leader', 'created_at',
        ).order_by(order_col)[:100])

        return {'sub_section': 'proposals', 'summary': summary, 'pipeline': pipeline, 'rows': rows}

    else:
        # Work in Hand
        qs = qs.filter(status__in=['In Progress', 'Not Started', 'Ongoing'])

        rows = list(qs.values(
            'id', 'assignment_no', 'title', 'office_id', 'client',
            'gross_value', 'status', 'domain', 'physical_progress_percent',
            'team_leader', 'workflow_stage', 'target_date',
        ).order_by('-gross_value')[:100])

        active_count = len(rows)
        total_value = sum(r.get('gross_value', 0) or 0 for r in rows)

        # Upcoming milestones (next 30 days)
        scoped_ids = list(qs.values_list('id', flat=True))
        upcoming_milestones = Milestone.objects.filter(
            assignment_id__in=scoped_ids,
            target_date__gte=today,
            target_date__lte=today + timedelta(days=30),
        ).exclude(status__in=['Completed', 'Cancelled']).count()

        summary = {
            'active_count': active_count,
            'total_value': total_value,
            'upcoming_milestones': upcoming_milestones,
        }

        return {'sub_section': 'work_in_hand', 'summary': summary, 'rows': rows}


# =========================================================================
# Main Dashboard View
# =========================================================================

@login_required
def dashboard_view(request):
    """Display the main dashboard with 4 MIS tabs and role-based views.

    RD Heads and Group Heads are redirected to the Head Assignment Hub
    on first visit (unless they explicitly navigate to dashboard).
    """
    user = request.user

    # Redirect Heads to assignment hub (unless they chose dashboard explicitly)
    role = getattr(user, "admin_role_id", "") or ""
    if role in ("RD Head", "Group Head") and "stay" not in request.GET:
        from django.shortcuts import redirect
        return redirect("core:head_hub")

    active_tab = request.GET.get('active_tab', 'default_mis')
    if active_tab not in VALID_TABS:
        active_tab = TAB_MIGRATION.get(active_tab, 'default_mis')

    current_fy = request.GET.get('fy') or _get_current_fy()
    fy_progress = _calculate_fy_progress()

    sub_view = request.GET.get('sub_view', '')
    sub_id = request.GET.get('sub_id', '')
    filter_office = request.GET.get('filter_office', '')
    filter_status = request.GET.get('filter_status', '')
    filter_domain = request.GET.get('filter_domain', '')
    sub_section = request.GET.get('sub_section', 'proposals')
    sort_by = request.GET.get('sort_by', '')
    sort_order = request.GET.get('sort_order', 'desc')

    active_role, scope_type, scope_value = _get_active_role_info(user)

    # Get role-based filter
    role_offices = []
    role_groups = []
    if active_role in ('DDG-I', 'DDG-II'):
        role_offices = _get_offices_for_ddg(active_role)
        role_groups = _get_groups_for_ddg(active_role)

    role_q, view_title, view_type, is_individual = _build_role_filter(
        active_role, scope_value, user, role_offices, role_groups
    )

    # Back-compat: filter_office -> sub_view=team_leaders&sub_id=filter_office
    if filter_office and not sub_view:
        sub_view = 'team_leaders'
        sub_id = filter_office

    # Determine default sub_view based on role
    if not sub_view:
        if active_role in ('DG', 'DDG-I', 'DDG-II', 'ADMIN'):
            sub_view = 'entities'
        elif active_role in ('GROUP_HEAD', 'RD_HEAD'):
            sub_view = 'team_leaders'
        elif active_role == 'TEAM_LEADER':
            sub_view = 'officers'
        else:
            sub_view = 'items'

    if sub_view not in ('entities', 'team_leaders', 'officers', 'items'):
        sub_view = 'items'

    # Available FYs
    financial_years = _get_available_fys()

    # Statuses for filter dropdown
    statuses = list(
        Assignment.objects.filter(status__isnull=False)
        .values_list('status', flat=True).distinct().order_by('status')
    )

    # Offices for filter dropdown
    offices_list = list(
        Office.objects.values('office_id', 'office_name').order_by('office_id')
    )

    # Domains for filter dropdown
    domains_list = list(
        Assignment.objects.filter(domain__isnull=False)
        .exclude(domain='')
        .values_list('domain', flat=True).distinct().order_by('domain')
    )

    # Dispatch to tab-specific query functions
    tab_data = {}
    sub_rows = []
    items = []
    breadcrumbs = []

    if active_tab == 'default_mis':
        tab_data = _get_default_mis_data(
            active_role, scope_value, user, current_fy,
            role_offices, role_groups
        )
        # Drill-down support
        if sub_view in ('team_leaders', 'officers', 'items') and sub_id:
            if sub_view == 'team_leaders':
                sub_rows = _get_tl_rows(sub_id, current_fy)
            elif sub_view == 'officers':
                sub_rows = _get_officer_rows(sub_id, current_fy)
            elif sub_view == 'items':
                items = _get_items_for_officer(sub_id, filter_status or None)

        breadcrumbs = _build_breadcrumbs(
            sub_view, sub_id, active_tab, current_fy, active_role, scope_value
        )

    elif active_tab == 'physical_progress':
        tab_data = _get_physical_progress_data(
            role_q, is_individual, user, current_fy, filter_office or None
        )

    elif active_tab == 'financial_progress':
        tab_data = _get_financial_progress_data(
            role_q, is_individual, user, current_fy, filter_office or None
        )

    elif active_tab == 'business_mis':
        tab_data = _get_business_mis_data(
            role_q, is_individual, user, current_fy,
            sub_section, filter_office or None, filter_status or None,
            filter_domain or None, sort_by or None, sort_order
        )

    context = {
        'user': user,
        'view': view_type,
        'view_title': view_title,
        'active_role': active_role,
        'scope_value': scope_value,
        'active_tab': active_tab,
        'current_fy': current_fy,
        'financial_years': financial_years,
        'tab_data': tab_data,
        'items': items,
        'sub_view': sub_view,
        'sub_id': sub_id,
        'sub_rows': sub_rows,
        'breadcrumbs': breadcrumbs,
        'statuses': statuses,
        'offices_list': offices_list,
        'domains_list': domains_list,
        'filter_office': filter_office,
        'filter_status': filter_status,
        'filter_domain': filter_domain,
        'sub_section': sub_section,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'fy_progress': fy_progress,
        'role_offices': role_offices,
        'role_groups': role_groups,
    }

    return render(request, 'dashboard.html', context)


# =========================================================================
# Dashboard Summary View
# =========================================================================

@login_required
def dashboard_summary_view(request):
    """Display summary statistics for the dashboard."""
    user = request.user
    office_id = user.office_id_value

    # Aggregate from assignments in user's office
    agg = Assignment.objects.filter(office_id=office_id).aggregate(
        total_assignments=Count('id'),
        total_projects=Count('id', filter=Q(type='ASSIGNMENT')),
        total_trainings=Count('id', filter=Q(type='TRAINING')),
        total_revenue=Coalesce(Sum('total_revenue'), 0.0),
        total_received=Coalesce(Sum('amount_received'), 0.0),
        total_value=Coalesce(Sum('gross_value'), 0.0),
        total_invoiced=Coalesce(Sum('invoice_amount'), 0.0),
        total_expenditure=Coalesce(Sum('total_expenditure'), 0.0),
        total_in_progress=Count('id', filter=Q(status__in=['In Progress', 'Ongoing'])),
        total_completed=Count('id', filter=Q(status='Completed')),
    )

    # Pending invoices
    pending_invoices = InvoiceRequest.objects.filter(
        assignment__office_id=office_id,
        status='PENDING',
    ).count()
    agg['pending_invoices'] = pending_invoices

    # My total share
    my_share = RevenueShare.objects.filter(
        officer_id=user.officer_id
    ).aggregate(
        total=Coalesce(Sum('share_amount'), 0.0)
    )['total']
    agg['my_total_share'] = my_share

    return render(request, 'dashboard_summary.html', {
        'user': user,
        'summary': agg,
    })


# =========================================================================
# API: Monthly Breakdown (JSON for charts)
# =========================================================================

@login_required
def monthly_breakdown_api(request):
    """Return breakdown data for a metric as JSON (for Chart.js)."""
    tab = request.GET.get('tab', 'assignments')
    metric = request.GET.get('metric', 'billing')
    fy = request.GET.get('fy') or _get_current_fy()
    view_mode = request.GET.get('view', 'monthly')

    fy_start, fy_end = _get_fy_date_range(fy)
    user = request.user
    active_role, scope_type, scope_value = _get_active_role_info(user)

    role_offices = []
    role_groups = []
    if active_role in ('DDG-I', 'DDG-II'):
        role_offices = _get_offices_for_ddg(active_role)
        role_groups = _get_groups_for_ddg(active_role)

    role_q, view_title, view_type, is_individual = _build_role_filter(
        active_role, scope_value, user, role_offices, role_groups
    )

    # Narrow scope for sub-views
    sub_view = request.GET.get('sub_view', '')
    sub_id = request.GET.get('sub_id', '')
    if sub_id and sub_view:
        if sub_view == 'team_leaders':
            role_q = Q(office_id=sub_id)
            is_individual = False
        elif sub_view == 'officers':
            role_q = Q(team_leader=sub_id)
            is_individual = False
        elif sub_view == 'items':
            is_individual = True

    # Determine type filters
    if tab in ('total_real_revenue', 'total_revenue'):
        type_filters = ['ASSIGNMENT', 'TRAINING']
    elif tab == 'assignments':
        type_filters = ['ASSIGNMENT']
    elif tab == 'training':
        type_filters = ['TRAINING']
    else:
        type_filters = []

    month_labels = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
                    'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar']
    month_nums = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    monthly = [0.0] * 12

    if not type_filters:
        return JsonResponse({'labels': month_labels, 'data': monthly, 'metric': metric})

    for type_filter in type_filters:
        scoped = _get_scoped_assignments(role_q, is_individual, user).filter(type=type_filter)

        if metric == 'billing':
            # Invoice amounts by month of request
            inv_qs = InvoiceRequest.objects.filter(
                assignment__in=scoped, fy_period=fy,
            ).annotate(
                m=ExtractMonth('requested_at')
            ).values('m').annotate(
                amt=Coalesce(Sum('invoice_amount'), 0.0)
            )
            for row in inv_qs:
                m = row['m']
                if m in month_nums:
                    monthly[month_nums.index(m)] += round(row['amt'] or 0, 2)

        elif metric == 'payments':
            pay_qs = PaymentReceipt.objects.filter(
                invoice_request__assignment__in=scoped, fy_period=fy,
            ).annotate(
                m=ExtractMonth('receipt_date')
            ).values('m').annotate(
                amt=Coalesce(Sum('amount_received'), 0.0)
            )
            for row in pay_qs:
                m = row['m']
                if m in month_nums:
                    monthly[month_nums.index(m)] += round(row['amt'] or 0, 2)

        elif metric == 'expenses':
            exp_qs = ExpenditureEntry.objects.filter(
                assignment__in=scoped, fy_period=fy,
            ).annotate(
                m=ExtractMonth('entry_date')
            ).values('m').annotate(
                amt=Coalesce(Sum('amount'), 0.0)
            )
            for row in exp_qs:
                m = row['m']
                if m in month_nums:
                    monthly[month_nums.index(m)] += round(row['amt'] or 0, 2)

        elif metric == 'active_count':
            active_qs = scoped.filter(
                status__in=['In Progress', 'Not Started', 'Ongoing'],
                start_date__gte=fy_start, start_date__lte=fy_end,
            ).annotate(
                m=ExtractMonth('start_date')
            ).values('m').annotate(amt=Count('id'))
            for row in active_qs:
                m = row['m']
                if m in month_nums:
                    monthly[month_nums.index(m)] += row['amt'] or 0

        elif metric == 'targeted':
            targeted_qs = scoped.filter(
                start_date__gte=fy_start, start_date__lte=fy_end,
            ).annotate(
                m=ExtractMonth('start_date')
            ).values('m').annotate(
                amt=Coalesce(Sum('gross_value'), 0.0)
            )
            for row in targeted_qs:
                m = row['m']
                if m in month_nums:
                    monthly[month_nums.index(m)] += round(row['amt'] or 0, 2)

    # Convert to requested view
    if view_mode == 'quarterly':
        quarterly = [
            round(sum(monthly[0:3]), 2),
            round(sum(monthly[3:6]), 2),
            round(sum(monthly[6:9]), 2),
            round(sum(monthly[9:12]), 2),
        ]
        return JsonResponse({
            'labels': ['Q1 (Apr-Jun)', 'Q2 (Jul-Sep)', 'Q3 (Oct-Dec)', 'Q4 (Jan-Mar)'],
            'data': quarterly,
            'metric': metric,
            'fy': fy,
        })
    elif view_mode == 'till_date':
        return JsonResponse({
            'labels': [f'FY {fy} Total'],
            'data': [round(sum(monthly), 2)],
            'metric': metric,
            'fy': fy,
        })
    else:
        return JsonResponse({
            'labels': month_labels,
            'data': monthly,
            'metric': metric,
            'fy': fy,
        })


# =========================================================================
# API: Business MIS (JSON for dynamic filtering)
# =========================================================================

@login_required
def business_mis_api(request):
    """JSON API for Tab D (Business MIS) dynamic filtering."""
    user = request.user
    fy = request.GET.get('fy') or _get_current_fy()
    sub_section = request.GET.get('sub_section', 'proposals')
    filter_office = request.GET.get('filter_office', '') or None
    filter_domain = request.GET.get('filter_domain', '') or None
    filter_status = request.GET.get('filter_status', '') or None
    sort_by = request.GET.get('sort_by', '') or None
    sort_order = request.GET.get('sort_order', 'desc')

    active_role, scope_type, scope_value = _get_active_role_info(user)
    role_offices = []
    role_groups = []
    if active_role in ('DDG-I', 'DDG-II'):
        role_offices = _get_offices_for_ddg(active_role)
        role_groups = _get_groups_for_ddg(active_role)

    role_q, _, _, is_individual = _build_role_filter(
        active_role, scope_value, user, role_offices, role_groups
    )

    data = _get_business_mis_data(
        role_q, is_individual, user, fy,
        sub_section, filter_office, filter_status, filter_domain,
        sort_by, sort_order
    )

    # Convert dates to strings for JSON serialization
    if 'rows' in data:
        for row in data['rows']:
            for k, v in row.items():
                if isinstance(v, (date,)):
                    row[k] = v.isoformat()
                elif hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()

    return JsonResponse(data)
