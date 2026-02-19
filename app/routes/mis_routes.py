"""
MIS Analytics Command Center: 6-tab dashboard with interactive Chart.js visualizations.
Tabs: Executive Summary, Office Performance, Activity & Domain, Financial Deep-Dive,
      Delays & Alerts, Officer & Client.
"""
import csv
import io
from typing import Optional
from datetime import datetime, date
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, StreamingResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user
from app.templates_config import templates
from app.config import SHOW_RANKINGS, REVENUE_WEIGHTAGE_REAL, REVENUE_WEIGHTAGE_NOTIONAL
from app.roles import get_user_role, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II, ROLE_ADMIN

router = APIRouter()

VALID_TABS = {'executive', 'office', 'activity', 'financial', 'delays', 'officer_client'}


def get_financial_years():
    """Generate list of financial years for filter dropdown."""
    current_year = datetime.now().year
    years = []
    for y in range(current_year - 5, current_year + 2):
        years.append(f"{y}-{str(y+1)[-2:]}")
    return years


def parse_financial_year(fy_str: str):
    """Parse financial year string to start and end dates."""
    if not fy_str or '-' not in fy_str:
        return None, None
    try:
        start_year = int(fy_str.split('-')[0])
        return date(start_year, 4, 1), date(start_year + 1, 3, 31)
    except:
        return None, None


def calculate_fy_progress():
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


def _date_diff_sql(column):
    """SQL expression for days since a date column (dual DB compatible)."""
    if USE_POSTGRES:
        return f"(CURRENT_DATE - {column}::date)"
    return f"CAST(julianday('now') - julianday({column}) AS INTEGER)"


def _build_base_filters(ph, financial_year, filter_office, filter_domain, filter_type, date_from, date_to):
    """Build shared WHERE clause and params from filter inputs."""
    conditions = "WHERE 1=1"
    params = []
    fy_start, fy_end = parse_financial_year(financial_year)
    if fy_start and fy_end:
        conditions += f" AND (a.start_date BETWEEN {ph} AND {ph} OR a.work_order_date BETWEEN {ph} AND {ph})"
        params.extend([fy_start.isoformat(), fy_end.isoformat(), fy_start.isoformat(), fy_end.isoformat()])
    if date_from:
        conditions += f" AND (a.start_date >= {ph} OR a.work_order_date >= {ph})"
        params.extend([date_from, date_from])
    if date_to:
        conditions += f" AND (a.start_date <= {ph} OR a.work_order_date <= {ph})"
        params.extend([date_to, date_to])
    if filter_office:
        conditions += f" AND a.office_id = {ph}"
        params.append(filter_office)
    if filter_domain:
        conditions += f" AND a.domain = {ph}"
        params.append(filter_domain)
    if filter_type:
        conditions += f" AND a.type = {ph}"
        params.append(filter_type)
    return conditions, params, fy_start, fy_end


# ---------------------------------------------------------------------------
# Tab data loaders
# ---------------------------------------------------------------------------

def _load_office_data(cursor, ph, financial_year, base_conditions, params, fy_progress, can_see_rankings):
    """Load office-wise target vs achievement data (used by Executive & Office tabs)."""
    office_query = f"""
        SELECT a.office_id, o.office_name, o.officer_count, o.annual_revenue_target,
            COALESCE(fyt.annual_target, o.annual_revenue_target) as target,
            COALESCE(fyt.training_target, 0) as training_target,
            COALESCE(fyt.lecture_target, 0) as lecture_target,
            COUNT(*) as assignment_count,
            SUM(COALESCE(a.total_revenue, 0)) as total_revenue,
            SUM(CASE WHEN a.type = 'ASSIGNMENT' THEN COALESCE(a.total_revenue, 0) ELSE 0 END) as assignment_revenue,
            SUM(CASE WHEN a.type = 'TRAINING' THEN COALESCE(a.total_revenue, 0) ELSE 0 END) as training_revenue,
            SUM(COALESCE(a.amount_received, 0)) as deposits,
            SUM(COALESCE(a.total_expenditure, 0)) as total_expenditure,
            SUM(COALESCE(a.surplus_deficit, 0)) as surplus_deficit,
            SUM(CASE WHEN a.type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as project_count,
            SUM(CASE WHEN a.type = 'TRAINING' THEN 1 ELSE 0 END) as training_count,
            AVG(COALESCE(a.physical_progress_percent, 0)) as avg_physical_progress
        FROM assignments a
        LEFT JOIN offices o ON a.office_id = o.office_id
        LEFT JOIN financial_year_targets fyt ON a.office_id = fyt.office_id AND fyt.financial_year = {ph}
        {base_conditions}
        GROUP BY a.office_id, o.office_name, o.officer_count, o.annual_revenue_target,
                 fyt.annual_target, fyt.training_target, fyt.lecture_target
        ORDER BY total_revenue DESC
    """
    cursor.execute(office_query, [financial_year] + params)
    office_data = [dict(row) for row in cursor.fetchall()]

    # Notional revenue
    cursor.execute("""SELECT office_id, COALESCE(SUM(notional_value), 0) as notional_revenue
        FROM non_revenue_suggestions WHERE status = 'COMPLETED' GROUP BY office_id""")
    notional_by_office = {row['office_id']: row['notional_revenue'] for row in cursor.fetchall()}

    for o in office_data:
        o['notional_revenue'] = notional_by_office.get(o['office_id'], 0)
        o['total_contribution'] = ((o['total_revenue'] or 0) * REVENUE_WEIGHTAGE_REAL) + (o['notional_revenue'] * REVENUE_WEIGHTAGE_NOTIONAL)
        target = o['target'] or 0
        o['prorata_target'] = round(target * fy_progress, 2)
        o['achievement_pct'] = round((o['total_contribution'] / target * 100), 1) if target > 0 else 0
        o['prorata_achievement_pct'] = round((o['total_contribution'] / o['prorata_target'] * 100), 1) if o['prorata_target'] > 0 else 0
        o['surplus_deficit_pct'] = round((o['surplus_deficit'] / o['total_revenue'] * 100), 1) if o['total_revenue'] > 0 else 0

    # Rankings
    if can_see_rankings:
        sorted_offices = sorted([o for o in office_data if o['achievement_pct'] > 0],
                                key=lambda x: x['achievement_pct'], reverse=True)
        top_3 = set(o['office_id'] for o in sorted_offices[:3])
        bottom_3 = set(o['office_id'] for o in sorted_offices[-3:]) if len(sorted_offices) > 3 else set()
    else:
        top_3, bottom_3 = set(), set()
    for o in office_data:
        o['is_top'] = o['office_id'] in top_3
        o['is_bottom'] = o['office_id'] in bottom_3 and o['office_id'] not in top_3

    office_data = sorted(office_data, key=lambda x: x['achievement_pct'] or 0, reverse=True)
    return office_data, notional_by_office


def _compute_totals(office_data, domain_data, fy_progress):
    """Compute summary totals from office data."""
    total_target = sum(o['target'] or 0 for o in office_data)
    total_revenue = sum(o['total_revenue'] or 0 for o in office_data)
    total_contribution = sum(o.get('total_contribution', o['total_revenue'] or 0) or 0 for o in office_data)
    total_expenditure = sum(o['total_expenditure'] or 0 for o in office_data)
    prorata_target = round(total_target * fy_progress, 2)
    avg_phys = sum(o['avg_physical_progress'] or 0 for o in office_data) / len(office_data) if office_data else 0
    return {
        'total_assignments': sum(o['assignment_count'] for o in office_data),
        'total_target': total_target,
        'prorata_target': prorata_target,
        'total_revenue': total_revenue,
        'assignment_revenue': sum(o.get('assignment_revenue', 0) or 0 for o in office_data),
        'training_revenue': sum(o.get('training_revenue', 0) or 0 for o in office_data),
        'notional_revenue': sum(o.get('notional_revenue', 0) or 0 for o in office_data),
        'total_contribution': total_contribution,
        'total_expenditure': total_expenditure,
        'surplus_deficit': total_revenue - total_expenditure,
        'achievement_pct': round((total_contribution / prorata_target * 100), 1) if prorata_target > 0 else 0,
        'overall_achievement_pct': round((total_contribution / total_target * 100), 1) if total_target > 0 else 0,
        'total_offices': len(office_data),
        'total_officers': sum(o['officer_count'] or 0 for o in office_data),
        'total_domains': len(domain_data) if domain_data else 0,
        'avg_physical_progress': round(avg_phys, 1),
        'fy_progress_pct': round(fy_progress * 100, 1),
    }


def _load_officer_data(cursor, ph, fy_start, fy_end, filter_office, date_from, date_to, fy_progress, can_see_rankings):
    """Load officer-wise target vs achievement."""
    officer_conditions = "WHERE 1=1"
    officer_params = []
    if fy_start and fy_end:
        officer_conditions += f" AND (a.start_date BETWEEN {ph} AND {ph} OR a.work_order_date BETWEEN {ph} AND {ph})"
        officer_params.extend([fy_start.isoformat(), fy_end.isoformat(), fy_start.isoformat(), fy_end.isoformat()])
    if date_from:
        officer_conditions += f" AND (a.start_date >= {ph} OR a.work_order_date >= {ph})"
        officer_params.extend([date_from, date_from])
    if date_to:
        officer_conditions += f" AND (a.start_date <= {ph} OR a.work_order_date <= {ph})"
        officer_params.extend([date_to, date_to])
    if filter_office:
        officer_conditions += f" AND a.office_id = {ph}"
        officer_params.append(filter_office)

    officer_query = f"""
        SELECT off.officer_id, off.name, off.office_id, off.designation, off.annual_target,
            COALESCE(rd.assignment_count, 0) as assignment_count,
            COALESCE(rd.total_share_amount, 0) as total_share_amount,
            COALESCE(rd.avg_share_percent, 0) as avg_share_percent
        FROM officers off
        LEFT JOIN (
            SELECT rs.officer_id, COUNT(DISTINCT rs.assignment_id) as assignment_count,
                SUM(rs.share_amount) as total_share_amount, AVG(rs.share_percent) as avg_share_percent
            FROM revenue_shares rs JOIN assignments a ON rs.assignment_id = a.id
            {officer_conditions} GROUP BY rs.officer_id
        ) rd ON off.officer_id = rd.officer_id
        WHERE off.is_active = 1
        {f"AND off.office_id = {ph}" if filter_office else ""}
        ORDER BY total_share_amount DESC
    """
    cursor.execute(officer_query, officer_params + ([filter_office] if filter_office else []))
    officer_data = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""SELECT officer_id, COALESCE(SUM(notional_value), 0) as notional_revenue
        FROM non_revenue_suggestions WHERE status = 'COMPLETED' AND officer_id IS NOT NULL GROUP BY officer_id""")
    notional_by_officer = {row['officer_id']: row['notional_revenue'] for row in cursor.fetchall()}

    for o in officer_data:
        target = o['annual_target'] or 60.0
        o['prorata_target'] = round(target * fy_progress, 2)
        o['real_revenue'] = o['total_share_amount'] or 0
        o['notional_revenue'] = notional_by_officer.get(o['officer_id'], 0)
        o['total_contribution'] = (o['real_revenue'] * REVENUE_WEIGHTAGE_REAL) + (o['notional_revenue'] * REVENUE_WEIGHTAGE_NOTIONAL)
        o['achievement_pct'] = round((o['total_contribution'] / target * 100), 1) if target > 0 else 0
        o['prorata_achievement_pct'] = round((o['total_contribution'] / o['prorata_target'] * 100), 1) if o['prorata_target'] > 0 else 0

    if can_see_rankings:
        sorted_off = sorted([o for o in officer_data if o['achievement_pct'] > 0],
                            key=lambda x: x['achievement_pct'], reverse=True)
        top_10 = set(o['officer_id'] for o in sorted_off[:10])
        bottom_10 = set(o['officer_id'] for o in sorted_off[-10:]) if len(sorted_off) > 10 else set()
    else:
        top_10, bottom_10 = set(), set()
    for o in officer_data:
        o['is_top'] = o['officer_id'] in top_10
        o['is_bottom'] = o['officer_id'] in bottom_10 and o['officer_id'] not in top_10

    return sorted(officer_data, key=lambda x: x['achievement_pct'] or 0, reverse=True)


def _load_domain_data(cursor, ph, base_conditions, params):
    """Load domain-wise revenue aggregation."""
    cursor.execute(f"""
        SELECT COALESCE(a.domain, 'Unspecified') as domain, COUNT(*) as assignment_count,
            SUM(COALESCE(a.total_revenue, 0)) as total_revenue,
            SUM(COALESCE(a.total_expenditure, 0)) as total_expenditure,
            SUM(COALESCE(a.surplus_deficit, 0)) as surplus_deficit,
            AVG(COALESCE(a.physical_progress_percent, 0)) as avg_physical_progress
        FROM assignments a {base_conditions}
        GROUP BY COALESCE(a.domain, 'Unspecified') ORDER BY total_revenue DESC
    """, params)
    return [dict(row) for row in cursor.fetchall()]


def _load_progress_by_status(cursor, ph, base_conditions, params):
    """Load status distribution."""
    cursor.execute(f"""
        SELECT a.status, COUNT(*) as count,
            AVG(COALESCE(a.physical_progress_percent, 0)) as avg_progress,
            SUM(COALESCE(a.total_revenue, 0)) as total_revenue
        FROM assignments a {base_conditions} GROUP BY a.status ORDER BY count DESC
    """, params)
    return [dict(row) for row in cursor.fetchall()]


def _load_activity_data(cursor, ph, base_conditions, params):
    """Load activity type breakdown + type-by-office cross-tab."""
    # Type breakdown
    cursor.execute(f"""
        SELECT COALESCE(a.type, 'ASSIGNMENT') as type, COUNT(*) as count,
            SUM(COALESCE(a.gross_value, 0)) as gross_value,
            SUM(COALESCE(a.total_revenue, 0)) as total_revenue,
            SUM(COALESCE(a.total_expenditure, 0)) as total_expenditure,
            AVG(COALESCE(a.physical_progress_percent, 0)) as avg_progress
        FROM assignments a {base_conditions} GROUP BY COALESCE(a.type, 'ASSIGNMENT') ORDER BY total_revenue DESC
    """, params)
    type_data = [dict(row) for row in cursor.fetchall()]

    # Type-by-office cross-tab
    cursor.execute(f"""
        SELECT a.office_id, COALESCE(a.type, 'ASSIGNMENT') as type, COUNT(*) as count,
            SUM(COALESCE(a.total_revenue, 0)) as total_revenue
        FROM assignments a {base_conditions}
        GROUP BY a.office_id, COALESCE(a.type, 'ASSIGNMENT') ORDER BY a.office_id
    """, params)
    type_by_office_raw = [dict(row) for row in cursor.fetchall()]

    # Pivot: {office_id: {type: revenue}}
    type_by_office = {}
    for row in type_by_office_raw:
        oid = row['office_id']
        if oid not in type_by_office:
            type_by_office[oid] = {'office_id': oid, 'ASSIGNMENT': 0, 'TRAINING': 0}
        type_by_office[oid][row['type']] = float(row['total_revenue'] or 0)
    type_by_office = sorted(type_by_office.values(),
                            key=lambda x: x.get('ASSIGNMENT', 0) + x.get('TRAINING', 0), reverse=True)

    return type_data, type_by_office


def _load_financial_data(cursor, ph, filter_office):
    """Load financial deep-dive: revenue pipeline, invoice/payment aging, expenditure by category."""
    office_filter = ""
    oparams = []
    if filter_office:
        office_filter = f"AND a.office_id = {ph}"
        oparams = [filter_office]

    # Revenue pipeline: gross → invoiced → received
    cursor.execute(f"""
        SELECT COALESCE(SUM(a.gross_value), 0) as gross_value,
            COALESCE(SUM(a.invoice_amount), 0) as total_invoiced,
            COALESCE(SUM(a.amount_received), 0) as total_received,
            COALESCE(SUM(a.total_revenue), 0) as total_revenue,
            COALESCE(SUM(a.total_expenditure), 0) as total_expenditure
        FROM assignments a WHERE 1=1 {office_filter}
    """, oparams)
    row = cursor.fetchone()
    pipeline = dict(row) if row else {}
    pipeline['net_revenue'] = (pipeline.get('total_received') or 0) - (pipeline.get('total_expenditure') or 0)
    pipeline['collection_rate'] = round(
        (pipeline['total_received'] / pipeline['total_invoiced'] * 100), 1
    ) if pipeline.get('total_invoiced') else 0

    # Invoice aging: approved invoices without full payment
    date_diff = _date_diff_sql('ir.approved_at')
    cursor.execute(f"""
        SELECT ir.id, ir.request_number, ir.invoice_amount, ir.approved_at,
            a.assignment_no, a.title, a.office_id, {date_diff} as days_since
        FROM invoice_requests ir
        JOIN assignments a ON ir.assignment_id = a.id
        LEFT JOIN payment_receipts pr ON ir.id = pr.invoice_request_id
        WHERE ir.status IN ('APPROVED', 'INVOICED') AND pr.id IS NULL
        AND ir.approved_at IS NOT NULL {office_filter}
        ORDER BY days_since DESC
    """, oparams)
    invoice_aging_rows = [dict(row) for row in cursor.fetchall()]
    # Bucket them
    invoice_buckets = {'0-30': {'count': 0, 'value': 0}, '30-60': {'count': 0, 'value': 0},
                       '60-90': {'count': 0, 'value': 0}, '90+': {'count': 0, 'value': 0}}
    for r in invoice_aging_rows:
        d = r.get('days_since') or 0
        bucket = '0-30' if d <= 30 else '30-60' if d <= 60 else '60-90' if d <= 90 else '90+'
        invoice_buckets[bucket]['count'] += 1
        invoice_buckets[bucket]['value'] += float(r.get('invoice_amount') or 0)

    # Payment aging: invoices paid but time since approval to first payment
    date_diff_pay = _date_diff_sql('pr.receipt_date') if USE_POSTGRES else _date_diff_sql('pr.created_at')
    cursor.execute(f"""
        SELECT pr.id, pr.amount_received, pr.receipt_date, pr.created_at,
            ir.request_number, ir.invoice_amount, a.assignment_no, a.office_id,
            {_date_diff_sql('ir.approved_at')} as days_since_approval
        FROM payment_receipts pr
        JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
        JOIN assignments a ON ir.assignment_id = a.id
        WHERE ir.approved_at IS NOT NULL {office_filter}
        ORDER BY days_since_approval DESC
    """, oparams)
    payment_rows = [dict(row) for row in cursor.fetchall()]
    payment_buckets = {'0-30': {'count': 0, 'value': 0}, '30-60': {'count': 0, 'value': 0},
                       '60-90': {'count': 0, 'value': 0}, '90+': {'count': 0, 'value': 0}}
    for r in payment_rows:
        d = r.get('days_since_approval') or 0
        bucket = '0-30' if d <= 30 else '30-60' if d <= 60 else '60-90' if d <= 90 else '90+'
        payment_buckets[bucket]['count'] += 1
        payment_buckets[bucket]['value'] += float(r.get('amount_received') or 0)

    # Expenditure by category
    cursor.execute(f"""
        SELECT eh.category, eh.head_name,
            COALESCE(SUM(ei.estimated_amount), 0) as budgeted,
            COALESCE(SUM(ei.actual_amount), 0) as actual_spent
        FROM expenditure_heads eh
        LEFT JOIN expenditure_items ei ON eh.id = ei.head_id
        LEFT JOIN assignments a ON ei.assignment_id = a.id
        WHERE 1=1 {office_filter if filter_office else ""}
        GROUP BY eh.category, eh.head_name
        HAVING budgeted > 0 OR actual_spent > 0
        ORDER BY actual_spent DESC
    """, oparams if filter_office else [])
    expenditure_data = [dict(row) for row in cursor.fetchall()]

    return {
        'pipeline': pipeline,
        'invoice_buckets': invoice_buckets,
        'invoice_aging_rows': invoice_aging_rows[:20],
        'payment_buckets': payment_buckets,
        'expenditure_data': expenditure_data,
    }


def _load_delays_data(cursor, ph, filter_office):
    """Load delay data for all 4 delay types + office heatmap."""
    office_filter = ""
    oparams = []
    if filter_office:
        office_filter = f"AND a.office_id = {ph}"
        oparams = [filter_office]

    # Payment delays
    cursor.execute(f"""
        SELECT ir.id, ir.invoice_amount, ir.approved_at,
            a.assignment_no, a.title, a.office_id,
            {_date_diff_sql('ir.approved_at')} as delay_days
        FROM invoice_requests ir
        JOIN assignments a ON ir.assignment_id = a.id
        LEFT JOIN payment_receipts pr ON ir.id = pr.invoice_request_id
        WHERE ir.status IN ('APPROVED', 'INVOICED') AND pr.id IS NULL
        AND ir.approved_at IS NOT NULL {office_filter}
        ORDER BY delay_days DESC
    """, oparams)
    payment_delays = [dict(row) for row in cursor.fetchall()]

    # Invoice delays
    cursor.execute(f"""
        SELECT m.id, m.milestone_no, m.title as milestone_title, m.target_date,
            a.assignment_no, a.title, a.office_id,
            {_date_diff_sql('m.target_date')} as delay_days
        FROM milestones m JOIN assignments a ON m.assignment_id = a.id
        WHERE m.target_date < {'CURRENT_DATE' if USE_POSTGRES else "DATE('now')"}
        AND m.invoice_raised = 0 AND m.status != 'Cancelled' {office_filter}
        ORDER BY delay_days DESC
    """, oparams)
    invoice_delays = [dict(row) for row in cursor.fetchall()]

    # Milestone delays
    cursor.execute(f"""
        SELECT m.id, m.milestone_no, m.title as milestone_title, m.target_date, m.status,
            a.assignment_no, a.title, a.office_id,
            {_date_diff_sql('m.target_date')} as delay_days
        FROM milestones m JOIN assignments a ON m.assignment_id = a.id
        WHERE m.target_date < {'CURRENT_DATE' if USE_POSTGRES else "DATE('now')"}
        AND m.status NOT IN ('Completed', 'Cancelled') {office_filter}
        ORDER BY delay_days DESC
    """, oparams)
    milestone_delays = [dict(row) for row in cursor.fetchall()]

    # Activation delays
    cursor.execute(f"""
        SELECT a.id, a.assignment_no, a.title, a.office_id, a.workflow_stage,
            {_date_diff_sql('a.created_at')} as delay_days
        FROM assignments a
        WHERE a.workflow_stage IN ('REGISTRATION', 'TL_ASSIGNMENT', 'DETAIL_ENTRY')
        AND {_date_diff_sql('a.created_at')} > 30 {office_filter}
        ORDER BY delay_days DESC
    """, oparams)
    activation_delays = [dict(row) for row in cursor.fetchall()]

    # Build office heatmap: office × delay_type → count
    heatmap = {}
    for item in payment_delays:
        oid = item['office_id']
        heatmap.setdefault(oid, {'payment': 0, 'invoice': 0, 'milestone': 0, 'activation': 0})
        heatmap[oid]['payment'] += 1
    for item in invoice_delays:
        oid = item['office_id']
        heatmap.setdefault(oid, {'payment': 0, 'invoice': 0, 'milestone': 0, 'activation': 0})
        heatmap[oid]['invoice'] += 1
    for item in milestone_delays:
        oid = item['office_id']
        heatmap.setdefault(oid, {'payment': 0, 'invoice': 0, 'milestone': 0, 'activation': 0})
        heatmap[oid]['milestone'] += 1
    for item in activation_delays:
        oid = item['office_id']
        heatmap.setdefault(oid, {'payment': 0, 'invoice': 0, 'milestone': 0, 'activation': 0})
        heatmap[oid]['activation'] += 1
    # Sort by total delays
    heatmap_list = [{'office_id': k, **v, 'total': v['payment'] + v['invoice'] + v['milestone'] + v['activation']}
                    for k, v in heatmap.items()]
    heatmap_list.sort(key=lambda x: x['total'], reverse=True)

    return {
        'payment_delays': payment_delays[:30],
        'invoice_delays': invoice_delays[:30],
        'milestone_delays': milestone_delays[:30],
        'activation_delays': activation_delays[:30],
        'heatmap': heatmap_list,
        'summary': {
            'payment_count': len(payment_delays),
            'invoice_count': len(invoice_delays),
            'milestone_count': len(milestone_delays),
            'activation_count': len(activation_delays),
            'payment_value': sum(float(r.get('invoice_amount') or 0) for r in payment_delays),
        }
    }


def _load_client_data(cursor, ph, filter_office):
    """Load client-wise revenue contribution."""
    office_filter = ""
    oparams = []
    if filter_office:
        office_filter = f"AND a.office_id = {ph}"
        oparams = [filter_office]

    cursor.execute(f"""
        SELECT c.id, c.client_name, c.client_type,
            COUNT(DISTINCT ac.assignment_id) as assignment_count,
            COALESCE(SUM(a.gross_value), 0) as total_value,
            COALESCE(SUM(a.invoice_amount), 0) as invoiced,
            COALESCE(SUM(a.amount_received), 0) as received
        FROM clients c
        JOIN assignment_clients ac ON c.id = ac.client_id
        JOIN assignments a ON ac.assignment_id = a.id
        WHERE 1=1 {office_filter}
        GROUP BY c.id, c.client_name, c.client_type
        ORDER BY total_value DESC
    """, oparams)
    client_data = [dict(row) for row in cursor.fetchall()]
    return client_data


# ---------------------------------------------------------------------------
# Main MIS Dashboard route (6-tab Command Center)
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def mis_dashboard(
    request: Request,
    active_tab: Optional[str] = Query("executive"),
    financial_year: Optional[str] = Query(None),
    filter_office: Optional[str] = Query(None),
    filter_domain: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query("desc")
):
    """6-tab MIS Command Center with interactive Chart.js visualizations."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if active_tab not in VALID_TABS:
        active_tab = 'executive'

    # Default FY
    if not financial_year:
        today = date.today()
        if today.month >= 4:
            financial_year = f"{today.year}-{str(today.year + 1)[-2:]}"
        else:
            financial_year = f"{today.year - 1}-{str(today.year)[-2:]}"

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'
        base_conditions, params, fy_start, fy_end = _build_base_filters(
            ph, financial_year, filter_office, filter_domain, filter_type, date_from, date_to)

        user_role = get_user_role(user)
        can_see_rankings = user_role in [ROLE_DG, ROLE_DDG_I, ROLE_DDG_II, ROLE_ADMIN]

        # Filter options (always loaded)
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT domain FROM assignments WHERE domain IS NOT NULL ORDER BY domain")
        domains = [row['domain'] for row in cursor.fetchall()]

        # Tab data
        tab_data = {}
        office_data = []
        domain_data = []
        totals = {}

        if active_tab in ('executive', 'office'):
            office_data, _ = _load_office_data(cursor, ph, financial_year, base_conditions, params, fy_progress, can_see_rankings)
            domain_data = _load_domain_data(cursor, ph, base_conditions, params)
            totals = _compute_totals(office_data, domain_data, fy_progress)
            progress_by_status = _load_progress_by_status(cursor, ph, base_conditions, params)
            tab_data['office_data'] = office_data
            tab_data['domain_data'] = domain_data
            tab_data['totals'] = totals
            tab_data['progress_by_status'] = progress_by_status
            # For executive summary: extra KPIs
            if active_tab == 'executive':
                officer_data = _load_officer_data(cursor, ph, fy_start, fy_end, filter_office, date_from, date_to, fy_progress, can_see_rankings)
                tab_data['officer_data'] = officer_data
                # Overdue milestones count
                cursor.execute(f"""
                    SELECT COUNT(*) as cnt FROM milestones m JOIN assignments a ON m.assignment_id = a.id
                    WHERE m.target_date < {'CURRENT_DATE' if USE_POSTGRES else "DATE('now')"}
                    AND m.status NOT IN ('Completed', 'Cancelled')
                    {"AND a.office_id = " + ph if filter_office else ""}
                """, [filter_office] if filter_office else [])
                row = cursor.fetchone()
                tab_data['overdue_milestones'] = dict(row)['cnt'] if row else 0
                # Pending invoices
                cursor.execute(f"""
                    SELECT COUNT(*) as cnt, COALESCE(SUM(ir.invoice_amount), 0) as val
                    FROM invoice_requests ir JOIN assignments a ON ir.assignment_id = a.id
                    WHERE ir.status = 'PENDING'
                    {"AND a.office_id = " + ph if filter_office else ""}
                """, [filter_office] if filter_office else [])
                inv_row = cursor.fetchone()
                inv_dict = dict(inv_row) if inv_row else {}
                tab_data['pending_invoices_count'] = inv_dict.get('cnt', 0)
                tab_data['pending_invoices_value'] = float(inv_dict.get('val', 0) or 0)
                # Active assignments count
                cursor.execute(f"""
                    SELECT COUNT(*) as cnt FROM assignments a
                    WHERE a.workflow_stage = 'ACTIVE'
                    {"AND a.office_id = " + ph if filter_office else ""}
                """, [filter_office] if filter_office else [])
                row = cursor.fetchone()
                tab_data['active_assignments'] = dict(row)['cnt'] if row else 0

        elif active_tab == 'activity':
            domain_data = _load_domain_data(cursor, ph, base_conditions, params)
            type_data, type_by_office = _load_activity_data(cursor, ph, base_conditions, params)
            office_data, _ = _load_office_data(cursor, ph, financial_year, base_conditions, params, fy_progress, can_see_rankings)
            totals = _compute_totals(office_data, domain_data, fy_progress)
            tab_data['type_data'] = type_data
            tab_data['type_by_office'] = type_by_office
            tab_data['domain_data'] = domain_data
            tab_data['totals'] = totals

        elif active_tab == 'financial':
            financial_detail = _load_financial_data(cursor, ph, filter_office)
            tab_data['financial'] = financial_detail

        elif active_tab == 'delays':
            delays_detail = _load_delays_data(cursor, ph, filter_office)
            tab_data['delays'] = delays_detail

        elif active_tab == 'officer_client':
            officer_data = _load_officer_data(cursor, ph, fy_start, fy_end, filter_office, date_from, date_to, fy_progress, can_see_rankings)
            client_data = _load_client_data(cursor, ph, filter_office)
            tab_data['officer_data'] = officer_data
            tab_data['client_data'] = client_data
            tab_data['officer_summary'] = {
                'total_officers': len(officer_data),
                'avg_achievement': round(sum(o['achievement_pct'] for o in officer_data) / len(officer_data), 1) if officer_data else 0,
                'above_target': len([o for o in officer_data if o['prorata_achievement_pct'] >= 100]),
                'below_50': len([o for o in officer_data if 0 < o['achievement_pct'] < 50]),
            }
            tab_data['client_summary'] = {
                'total_clients': len(client_data),
                'top_client_revenue': max((float(c['total_value'] or 0) for c in client_data), default=0),
                'avg_revenue': round(sum(float(c['total_value'] or 0) for c in client_data) / len(client_data), 1) if client_data else 0,
            }

    return templates.TemplateResponse(
        "mis_dashboard.html",
        {
            "request": request,
            "user": user,
            "active_tab": active_tab,
            "tab_data": tab_data,
            "offices": offices,
            "domains": domains,
            "financial_years": get_financial_years(),
            "filter_office": filter_office,
            "filter_domain": filter_domain,
            "filter_type": filter_type,
            "financial_year": financial_year,
            "date_from": date_from,
            "date_to": date_to,
            "fy_progress": fy_progress,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "can_see_rankings": can_see_rankings,
            # Backward compat: pass top-level vars for existing drill-down pages
            "totals": totals if totals else {},
            "office_data": office_data,
            "domain_data": domain_data,
        }
    )


# ---------------------------------------------------------------------------
# CSV Export endpoint
# ---------------------------------------------------------------------------

@router.get("/export/csv")
async def export_csv(
    request: Request,
    tab: str = Query("office"),
    financial_year: Optional[str] = Query(None),
    filter_office: Optional[str] = Query(None),
    filter_domain: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Export current tab data as CSV."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not financial_year:
        today = date.today()
        if today.month >= 4:
            financial_year = f"{today.year}-{str(today.year + 1)[-2:]}"
        else:
            financial_year = f"{today.year - 1}-{str(today.year)[-2:]}"

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'
        base_conditions, params, fy_start, fy_end = _build_base_filters(
            ph, financial_year, filter_office, filter_domain, filter_type, date_from, date_to)
        can_see_rankings = get_user_role(user) in [ROLE_DG, ROLE_DDG_I, ROLE_DDG_II, ROLE_ADMIN]

        output = io.StringIO()
        writer = csv.writer(output)

        if tab in ('executive', 'office'):
            office_data, _ = _load_office_data(cursor, ph, financial_year, base_conditions, params, fy_progress, can_see_rankings)
            writer.writerow(['Office', 'Target', 'Pro-rata', 'Assignment Rev', 'Training Rev', 'Notional', 'Total', 'Achievement %', 'Expenditure', 'Surplus'])
            for o in office_data:
                writer.writerow([o['office_id'], o['target'], round(o['prorata_target'], 1),
                    round(o.get('assignment_revenue') or 0, 1), round(o.get('training_revenue') or 0, 1),
                    round(o.get('notional_revenue') or 0, 1), round(o.get('total_contribution') or 0, 1),
                    o['achievement_pct'], round(o['total_expenditure'] or 0, 1), round(o['surplus_deficit'] or 0, 1)])

        elif tab == 'delays':
            delays = _load_delays_data(cursor, ph, filter_office)
            writer.writerow(['Type', 'Assignment', 'Title', 'Office', 'Delay Days'])
            for d in delays['milestone_delays']:
                writer.writerow(['Milestone', d['assignment_no'], d.get('milestone_title', ''), d['office_id'], d['delay_days']])
            for d in delays['payment_delays']:
                writer.writerow(['Payment', d['assignment_no'], d.get('title', ''), d['office_id'], d['delay_days']])
            for d in delays['invoice_delays']:
                writer.writerow(['Invoice', d['assignment_no'], d.get('milestone_title', ''), d['office_id'], d['delay_days']])

        elif tab == 'officer_client':
            officer_data = _load_officer_data(cursor, ph, fy_start, fy_end, filter_office, date_from, date_to, fy_progress, can_see_rankings)
            writer.writerow(['Officer', 'Office', 'Target', 'Real Revenue', 'Notional', 'Total', 'Achievement %', 'Assignments'])
            for o in officer_data:
                writer.writerow([o['name'], o['office_id'], o['annual_target'] or 60,
                    round(o['real_revenue'], 1), round(o['notional_revenue'], 1),
                    round(o['total_contribution'], 1), o['achievement_pct'], o['assignment_count']])

        else:
            writer.writerow(['No data for this tab'])

    output.seek(0)
    filename = f"mis_{tab}_{financial_year}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/office/{office_id}", response_class=HTMLResponse)
async def office_detail(request: Request, office_id: str):
    """Detailed view for a specific office with target vs achievement."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get office info with target
        cursor.execute(f"""
            SELECT o.*, fyt.annual_target as fy_target, fyt.training_target, fyt.lecture_target
            FROM offices o
            LEFT JOIN financial_year_targets fyt ON o.office_id = fyt.office_id
                AND fyt.financial_year = {ph}
            WHERE o.office_id = {ph}
        """, (f"{date.today().year}-{str(date.today().year + 1)[-2:]}" if date.today().month >= 4
              else f"{date.today().year - 1}-{str(date.today().year)[-2:]}", office_id))
        office = cursor.fetchone()
        if not office:
            return RedirectResponse(url="/mis", status_code=302)
        office = dict(office)

        # Get assignments for this office with milestones count
        cursor.execute(f"""
            SELECT
                a.*,
                (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count,
                (SELECT COUNT(*) FROM milestones m WHERE m.assignment_id = a.id) as milestone_count,
                (SELECT COUNT(*) FROM milestones m WHERE m.assignment_id = a.id AND m.status = 'Completed') as completed_milestones
            FROM assignments a
            WHERE a.office_id = {ph}
            ORDER BY a.start_date DESC
        """, (office_id,))
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get ALL officers in this office with their targets and achievements
        cursor.execute(f"""
            SELECT
                o.*,
                COALESCE(SUM(rs.share_amount), 0) as total_share,
                COUNT(DISTINCT rs.assignment_id) as assignment_count
            FROM officers o
            LEFT JOIN revenue_shares rs ON o.officer_id = rs.officer_id
            WHERE o.office_id = {ph} AND o.is_active = 1
            GROUP BY o.officer_id
        """, (office_id,))
        officers = [dict(row) for row in cursor.fetchall()]

        # Get notional revenue for each officer in this office
        cursor.execute(f"""
            SELECT officer_id, COALESCE(SUM(notional_value), 0) as notional_revenue
            FROM non_revenue_suggestions
            WHERE status = 'COMPLETED' AND officer_id IS NOT NULL
            GROUP BY officer_id
        """)
        notional_by_officer = {row['officer_id']: row['notional_revenue'] for row in cursor.fetchall()}

        # Calculate achievement for each officer (weighted)
        for o in officers:
            target = o.get('annual_target', 60.0) or 60.0
            o['prorata_target'] = round(target * fy_progress, 2)
            o['real_revenue'] = o['total_share'] or 0
            o['notional_revenue'] = notional_by_officer.get(o['officer_id'], 0)
            o['total_contribution'] = (o['real_revenue'] * REVENUE_WEIGHTAGE_REAL) + (o['notional_revenue'] * REVENUE_WEIGHTAGE_NOTIONAL)
            o['achievement_pct'] = round((o['total_contribution'] / target * 100), 1) if target > 0 else 0

        # Sort officers by achievement % (not by total value)
        officers = sorted(officers, key=lambda x: x['achievement_pct'] or 0, reverse=True)

        # Get status breakdown for this office
        cursor.execute(f"""
            SELECT
                status,
                COUNT(*) as count,
                AVG(COALESCE(physical_progress_percent, 0)) as avg_progress
            FROM assignments
            WHERE office_id = {ph}
            GROUP BY status
            ORDER BY count DESC
        """, (office_id,))
        status_breakdown = [dict(row) for row in cursor.fetchall()]

        # Summary stats with target comparison (weighted revenue)
        target = office.get('fy_target') or office.get('annual_revenue_target') or 0
        total_revenue = sum(a['total_revenue'] or 0 for a in assignments)
        total_expenditure = sum(a['total_expenditure'] or 0 for a in assignments)
        # Get office notional revenue
        cursor.execute(f"""
            SELECT COALESCE(SUM(notional_value), 0) as notional_revenue
            FROM non_revenue_suggestions
            WHERE status = 'COMPLETED' AND office_id = {ph}
        """, (office_id,))
        office_notional_row = cursor.fetchone()
        office_notional_revenue = office_notional_row['notional_revenue'] if office_notional_row else 0
        total_contribution = (total_revenue * REVENUE_WEIGHTAGE_REAL) + (office_notional_revenue * REVENUE_WEIGHTAGE_NOTIONAL)
        prorata_target = round(target * fy_progress, 2)
        avg_progress = sum(a['physical_progress_percent'] or 0 for a in assignments) / len(assignments) if assignments else 0

        summary = {
            'total_assignments': len(assignments),
            'total_revenue': total_revenue,
            'notional_revenue': office_notional_revenue,
            'total_contribution': total_contribution,
            'total_expenditure': total_expenditure,
            'surplus_deficit': total_revenue - total_expenditure,
            'officer_count': office.get('officer_count', len(officers)),
            'annual_target': target,
            'prorata_target': prorata_target,
            'achievement_pct': round((total_contribution / prorata_target * 100), 1) if prorata_target > 0 else 0,
            'avg_progress': round(avg_progress, 1)
        }

    return templates.TemplateResponse(
        "office_detail.html",
        {
            "request": request,
            "user": user,
            "office": office,
            "assignments": assignments,
            "officers": officers,
            "summary": summary,
            "status_breakdown": status_breakdown,
            "fy_progress": fy_progress
        }
    )


@router.get("/officer/{officer_id}", response_class=HTMLResponse)
async def officer_detail(request: Request, officer_id: str):
    """Detailed view for a specific officer's revenue shares with target comparison."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get officer info
        cursor.execute(f"SELECT * FROM officers WHERE officer_id = {ph}", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/mis", status_code=302)
        officer = dict(officer)

        # Get revenue shares for this officer with assignment details
        cursor.execute(f"""
            SELECT
                rs.*,
                a.assignment_no,
                a.title,
                a.type,
                a.office_id,
                a.total_revenue,
                a.gross_value,
                a.status,
                a.physical_progress_percent,
                a.start_date,
                a.target_date
            FROM revenue_shares rs
            JOIN assignments a ON rs.assignment_id = a.id
            WHERE rs.officer_id = {ph}
            ORDER BY rs.share_amount DESC
        """, (officer_id,))
        shares = [dict(row) for row in cursor.fetchall()]

        # Get notional revenue for this officer
        cursor.execute(f"""
            SELECT COALESCE(SUM(notional_value), 0) as notional_revenue
            FROM non_revenue_suggestions
            WHERE status = 'COMPLETED' AND officer_id = {ph}
        """, (officer_id,))
        notional_row = cursor.fetchone()
        notional_revenue = notional_row['notional_revenue'] if notional_row else 0

        # Summary stats with target comparison (weighted revenue)
        target = officer.get('annual_target', 60.0) or 60.0
        total_share = sum(s['share_amount'] or 0 for s in shares)
        total_contribution = (total_share * REVENUE_WEIGHTAGE_REAL) + (notional_revenue * REVENUE_WEIGHTAGE_NOTIONAL)

        summary = {
            'total_assignments': len(shares),
            'total_share_amount': total_share,
            'real_revenue': total_share,
            'notional_revenue': notional_revenue,
            'total_contribution': total_contribution,
            'avg_share_percent': sum(s['share_percent'] or 0 for s in shares) / len(shares) if shares else 0,
            'annual_target': target,
            'prorata_target': round(target * fy_progress, 2),
            'achievement_pct': round((total_contribution / target * 100), 1) if target > 0 else 0,
            'prorata_achievement_pct': round((total_contribution / (target * fy_progress) * 100), 1) if target * fy_progress > 0 else 0
        }

    return templates.TemplateResponse(
        "officer_detail.html",
        {
            "request": request,
            "user": user,
            "officer": officer,
            "shares": shares,
            "summary": summary,
            "fy_progress": fy_progress
        }
    )


@router.get("/assignment/{assignment_id}/progress", response_class=HTMLResponse)
async def assignment_progress(request: Request, assignment_id: int):
    """View milestones and progress for a specific assignment."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get assignment details
        cursor.execute(f"SELECT * FROM assignments WHERE id = {ph}", (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            return RedirectResponse(url="/mis", status_code=302)
        assignment = dict(assignment)

        # Get milestones
        cursor.execute(f"""
            SELECT * FROM milestones
            WHERE assignment_id = {ph}
            ORDER BY milestone_no
        """, (assignment_id,))
        milestones = [dict(row) for row in cursor.fetchall()]

        # Get expenditure items
        cursor.execute(f"""
            SELECT ei.*, eh.category, eh.head_code, eh.head_name
            FROM expenditure_items ei
            JOIN expenditure_heads eh ON ei.head_id = eh.id
            WHERE ei.assignment_id = {ph}
            ORDER BY eh.category, eh.head_code
        """, (assignment_id,))
        expenditure_items = [dict(row) for row in cursor.fetchall()]

        # Group expenditure by category
        expenditure_by_category = {}
        for item in expenditure_items:
            cat = item['category']
            if cat not in expenditure_by_category:
                expenditure_by_category[cat] = {'items': [], 'estimated_total': 0, 'actual_total': 0}
            expenditure_by_category[cat]['items'].append(item)
            expenditure_by_category[cat]['estimated_total'] += item['estimated_amount'] or 0
            expenditure_by_category[cat]['actual_total'] += item['actual_amount'] or 0

        # Calculate summary
        completed_milestones = [m for m in milestones if m['status'] == 'Completed']
        summary = {
            'total_milestones': len(milestones),
            'completed_milestones': len(completed_milestones),
            'physical_progress': sum(m['revenue_percent'] for m in completed_milestones),
            'total_estimated_expenditure': sum(e['estimated_amount'] or 0 for e in expenditure_items),
            'total_actual_expenditure': sum(e['actual_amount'] or 0 for e in expenditure_items),
        }

    return templates.TemplateResponse(
        "assignment_progress.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "milestones": milestones,
            "expenditure_by_category": expenditure_by_category,
            "summary": summary
        }
    )


@router.get("/assignments", response_class=HTMLResponse)
async def assignments_list(
    request: Request,
    filter_office: Optional[str] = Query(None),
    filter_domain: Optional[str] = Query(None),
    filter_status: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None),
    value_min: Optional[float] = Query(None),
    value_max: Optional[float] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("revenue"),
    sort_order: Optional[str] = Query("desc")
):
    """Enhanced assignment list MIS with additional filters, columns, and summary totals."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Build query with filters
        conditions = "WHERE 1=1"
        params = []

        if filter_office:
            conditions += f" AND a.office_id = {ph}"
            params.append(filter_office)

        if filter_domain:
            conditions += f" AND a.domain = {ph}"
            params.append(filter_domain)

        if filter_status:
            conditions += f" AND a.status = {ph}"
            params.append(filter_status)

        if filter_type:
            conditions += f" AND a.type = {ph}"
            params.append(filter_type)

        if value_min is not None:
            conditions += f" AND COALESCE(a.total_value, 0) >= {ph}"
            params.append(value_min)

        if value_max is not None:
            conditions += f" AND COALESCE(a.total_value, 0) <= {ph}"
            params.append(value_max)

        if date_from:
            conditions += f" AND a.created_at >= {ph}"
            params.append(date_from)

        if date_to:
            conditions += f" AND a.created_at <= {ph}"
            params.append(date_to)

        # Determine sort column
        sort_column = "a.total_revenue"
        if sort_by == "timeline":
            sort_column = "a.timeline_progress_percent"
        elif sort_by == "physical":
            sort_column = "a.physical_progress_percent"
        elif sort_by == "value":
            sort_column = "a.total_value"
        elif sort_by == "expenditure":
            sort_column = "a.total_expenditure"
        elif sort_by == "received":
            sort_column = "a.amount_received"

        order = "DESC" if sort_order == "desc" else "ASC"

        query = f"""
            SELECT
                a.*,
                o.office_name,
                tl.name as team_leader_name,
                (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id) as milestone_count,
                (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id AND payment_received = 1) as paid_milestones,
                (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id AND invoice_raised = 1) as invoiced_milestones,
                (SELECT COUNT(*) FROM assignment_team WHERE assignment_id = a.id AND is_active = 1) as team_size
            FROM assignments a
            LEFT JOIN offices o ON a.office_id = o.office_id
            LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
            {conditions}
            ORDER BY {sort_column} {order}
        """

        cursor.execute(query, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get filter options
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT domain FROM assignments WHERE domain IS NOT NULL ORDER BY domain")
        domains = [row['domain'] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT status FROM assignments WHERE status IS NOT NULL ORDER BY status")
        statuses = [row['status'] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT type FROM assignments WHERE type IS NOT NULL ORDER BY type")
        types = [row['type'] for row in cursor.fetchall()]

        # Calculate summary totals
        summary = {
            'total_count': len(assignments),
            'total_value': sum(a.get('total_value') or 0 for a in assignments),
            'total_revenue': sum(a.get('total_revenue') or 0 for a in assignments),
            'total_invoiced': sum(a.get('invoice_amount') or 0 for a in assignments),
            'total_received': sum(a.get('amount_received') or 0 for a in assignments),
            'total_expenditure': sum(a.get('total_expenditure') or 0 for a in assignments),
            'avg_physical_progress': round(
                sum(a.get('physical_progress_percent') or 0 for a in assignments) / len(assignments), 1
            ) if assignments else 0,
            'avg_timeline_progress': round(
                sum(a.get('timeline_progress_percent') or 0 for a in assignments) / len(assignments), 1
            ) if assignments else 0
        }

    return templates.TemplateResponse(
        "assignments_list.html",
        {
            "request": request,
            "user": user,
            "assignments": assignments,
            "offices": offices,
            "domains": domains,
            "statuses": statuses,
            "types": types,
            "summary": summary,
            "filter_office": filter_office,
            "filter_domain": filter_domain,
            "filter_status": filter_status,
            "filter_type": filter_type,
            "value_min": value_min,
            "value_max": value_max,
            "date_from": date_from,
            "date_to": date_to,
            "sort_by": sort_by,
            "sort_order": sort_order
        }
    )


# ============================================
# TOP-DOWN MIS DRILL-DOWN ROUTES
# Multiple navigation paths:
#   Path A: NPC → Domain → Office → Assignment → Officer
#   Path B: NPC → Office → Domain → Assignment → Officer
#   Path C: NPC → Officer → Assignment (direct)
# ============================================

@router.get("/domain/{domain}", response_class=HTMLResponse)
async def domain_detail(
    request: Request,
    domain: str,
    filter_office: Optional[str] = Query(None)
):
    """
    Domain-level drill-down view.
    Path A: NPC → Domain → (Offices in this domain)
    Shows all offices working in this domain with their revenue.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get office breakdown for this domain
        cursor.execute(f"""
            SELECT
                a.office_id,
                o.office_name,
                COUNT(*) as assignment_count,
                SUM(COALESCE(a.total_revenue, 0)) as total_revenue,
                SUM(COALESCE(a.gross_value, 0)) as total_value,
                SUM(COALESCE(a.total_expenditure, 0)) as total_expenditure,
                AVG(COALESCE(a.physical_progress_percent, 0)) as avg_progress
            FROM assignments a
            LEFT JOIN offices o ON a.office_id = o.office_id
            WHERE a.domain = {ph}
            GROUP BY a.office_id, o.office_name
            ORDER BY total_revenue DESC
        """, (domain,))
        offices_in_domain = [dict(row) for row in cursor.fetchall()]

        # Get all assignments in this domain
        conditions = f"WHERE a.domain = {ph}"
        params = [domain]

        if filter_office:
            conditions += f" AND a.office_id = {ph}"
            params.append(filter_office)

        cursor.execute(f"""
            SELECT
                a.*,
                o.office_name,
                (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as team_size
            FROM assignments a
            LEFT JOIN offices o ON a.office_id = o.office_id
            {conditions}
            ORDER BY a.total_revenue DESC
        """, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get officer contributions in this domain
        cursor.execute(f"""
            SELECT
                rs.officer_id,
                off.name,
                off.office_id,
                off.designation,
                COUNT(DISTINCT rs.assignment_id) as assignment_count,
                SUM(rs.share_amount) as total_share
            FROM revenue_shares rs
            JOIN assignments a ON rs.assignment_id = a.id
            JOIN officers off ON rs.officer_id = off.officer_id
            WHERE a.domain = {ph}
            GROUP BY rs.officer_id, off.name, off.office_id, off.designation
            ORDER BY total_share DESC
            LIMIT 20
        """, (domain,))
        top_officers = [dict(row) for row in cursor.fetchall()]

        # Domain summary
        total_revenue = sum(o['total_revenue'] or 0 for o in offices_in_domain)
        total_value = sum(o['total_value'] or 0 for o in offices_in_domain)

        summary = {
            'total_offices': len(offices_in_domain),
            'total_assignments': sum(o['assignment_count'] for o in offices_in_domain),
            'total_revenue': total_revenue,
            'total_value': total_value,
            'total_expenditure': sum(o['total_expenditure'] or 0 for o in offices_in_domain),
            'avg_progress': sum(o['avg_progress'] or 0 for o in offices_in_domain) / len(offices_in_domain) if offices_in_domain else 0
        }

        # Get list of offices for filter
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        all_offices = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "mis_domain.html",
        {
            "request": request,
            "user": user,
            "domain": domain,
            "offices_in_domain": offices_in_domain,
            "assignments": assignments,
            "top_officers": top_officers,
            "summary": summary,
            "all_offices": all_offices,
            "filter_office": filter_office,
            "fy_progress": fy_progress,
            "breadcrumb": [
                {"label": "MIS Dashboard", "url": "/mis"},
                {"label": f"Domain: {domain}", "url": None}
            ]
        }
    )


@router.get("/domain/{domain}/office/{office_id}", response_class=HTMLResponse)
async def domain_office_detail(request: Request, domain: str, office_id: str):
    """
    Domain + Office drill-down view.
    Path A continued: NPC → Domain → Office → (Assignments)
    Shows assignments for a specific office within a specific domain.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get office info
        cursor.execute(f"SELECT * FROM offices WHERE office_id = {ph}", (office_id,))
        office = cursor.fetchone()
        if not office:
            return RedirectResponse(url=f"/mis/domain/{domain}", status_code=302)
        office = dict(office)

        # Get assignments for this domain + office combination
        cursor.execute(f"""
            SELECT
                a.*,
                (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as team_size,
                (SELECT COUNT(*) FROM milestones m WHERE m.assignment_id = a.id) as milestone_count
            FROM assignments a
            WHERE a.domain = {ph} AND a.office_id = {ph}
            ORDER BY a.total_revenue DESC
        """, (domain, office_id))
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get officers working on these assignments
        cursor.execute(f"""
            SELECT
                rs.officer_id,
                off.name,
                off.designation,
                COUNT(DISTINCT rs.assignment_id) as assignment_count,
                SUM(rs.share_amount) as total_share,
                AVG(rs.share_percent) as avg_share_pct
            FROM revenue_shares rs
            JOIN assignments a ON rs.assignment_id = a.id
            JOIN officers off ON rs.officer_id = off.officer_id
            WHERE a.domain = {ph} AND a.office_id = {ph}
            GROUP BY rs.officer_id, off.name, off.designation
            ORDER BY total_share DESC
        """, (domain, office_id))
        officers = [dict(row) for row in cursor.fetchall()]

        # Summary
        summary = {
            'total_assignments': len(assignments),
            'total_revenue': sum(a['total_revenue'] or 0 for a in assignments),
            'total_value': sum(a['gross_value'] or 0 for a in assignments),
            'total_officers': len(officers),
            'avg_progress': sum(a['physical_progress_percent'] or 0 for a in assignments) / len(assignments) if assignments else 0
        }

    return templates.TemplateResponse(
        "mis_domain_office.html",
        {
            "request": request,
            "user": user,
            "domain": domain,
            "office": office,
            "assignments": assignments,
            "officers": officers,
            "summary": summary,
            "fy_progress": fy_progress,
            "breadcrumb": [
                {"label": "MIS Dashboard", "url": "/mis"},
                {"label": f"Domain: {domain}", "url": f"/mis/domain/{domain}"},
                {"label": office['office_name'], "url": None}
            ]
        }
    )


@router.get("/officers", response_class=HTMLResponse)
async def officers_direct(
    request: Request,
    filter_office: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("achievement"),
    sort_order: Optional[str] = Query("desc")
):
    """
    Direct officer list without office grouping.
    Path C: NPC → Officer → (Assignments)
    Shows all officers ranked by achievement across the organization.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get all active officers with their revenue data
        conditions = "WHERE off.is_active = 1"
        params = []

        if filter_office:
            conditions += f" AND off.office_id = {ph}"
            params.append(filter_office)

        cursor.execute(f"""
            SELECT
                off.officer_id,
                off.name,
                off.office_id,
                off.designation,
                off.annual_target,
                COALESCE(revenue_data.assignment_count, 0) as assignment_count,
                COALESCE(revenue_data.total_share_amount, 0) as real_revenue,
                COALESCE(notional_data.notional_revenue, 0) as notional_revenue
            FROM officers off
            LEFT JOIN (
                SELECT
                    rs.officer_id,
                    COUNT(DISTINCT rs.assignment_id) as assignment_count,
                    SUM(rs.share_amount) as total_share_amount
                FROM revenue_shares rs
                GROUP BY rs.officer_id
            ) revenue_data ON off.officer_id = revenue_data.officer_id
            LEFT JOIN (
                SELECT
                    officer_id,
                    SUM(notional_value) as notional_revenue
                FROM non_revenue_suggestions
                WHERE status = 'COMPLETED'
                GROUP BY officer_id
            ) notional_data ON off.officer_id = notional_data.officer_id
            {conditions}
        """, params)
        officers = [dict(row) for row in cursor.fetchall()]

        # Calculate achievement percentages (weighted)
        for o in officers:
            target = o['annual_target'] or 60.0
            o['prorata_target'] = round(target * fy_progress, 2)
            o['total_contribution'] = ((o['real_revenue'] or 0) * REVENUE_WEIGHTAGE_REAL) + ((o['notional_revenue'] or 0) * REVENUE_WEIGHTAGE_NOTIONAL)
            o['achievement_pct'] = round((o['total_contribution'] / target * 100), 1) if target > 0 else 0
            o['prorata_achievement_pct'] = round((o['total_contribution'] / o['prorata_target'] * 100), 1) if o['prorata_target'] > 0 else 0

        # Sort officers
        if sort_by == "revenue":
            officers = sorted(officers, key=lambda x: x['total_contribution'] or 0, reverse=(sort_order == "desc"))
        elif sort_by == "name":
            officers = sorted(officers, key=lambda x: x['name'] or '', reverse=(sort_order == "desc"))
        else:  # achievement (default)
            officers = sorted(officers, key=lambda x: x['achievement_pct'] or 0, reverse=(sort_order == "desc"))

        # Rankings only visible to DDG/DG/ADMIN
        user_role = get_user_role(user)
        can_see_rankings = user_role in [ROLE_DG, ROLE_DDG_I, ROLE_DDG_II, ROLE_ADMIN]

        # Mark top and bottom performers
        if can_see_rankings:
            active_performers = [o for o in officers if o['achievement_pct'] > 0]
            top_10 = set(o['officer_id'] for o in active_performers[:10])
            bottom_10 = set(o['officer_id'] for o in active_performers[-10:]) if len(active_performers) > 10 else set()
        else:
            top_10 = set()
            bottom_10 = set()

        for o in officers:
            o['is_top'] = o['officer_id'] in top_10
            o['is_bottom'] = o['officer_id'] in bottom_10 and o['officer_id'] not in top_10

        # Get filter options
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices_list = [dict(row) for row in cursor.fetchall()]

        # Summary stats
        summary = {
            'total_officers': len(officers),
            'total_real_revenue': sum(o['real_revenue'] or 0 for o in officers),
            'total_notional_revenue': sum(o['notional_revenue'] or 0 for o in officers),
            'total_contribution': sum(o['total_contribution'] or 0 for o in officers),
            'avg_achievement_pct': sum(o['achievement_pct'] for o in officers) / len(officers) if officers else 0,
            'officers_above_target': len([o for o in officers if o['prorata_achievement_pct'] >= 100]),
            'officers_below_target': len([o for o in officers if 0 < o['prorata_achievement_pct'] < 100])
        }

    return templates.TemplateResponse(
        "mis_officers.html",
        {
            "request": request,
            "user": user,
            "officers": officers,
            "offices_list": offices_list,
            "summary": summary,
            "filter_office": filter_office,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "fy_progress": fy_progress,
            "can_see_rankings": can_see_rankings,
            "breadcrumb": [
                {"label": "MIS Dashboard", "url": "/mis"},
                {"label": "All Officers", "url": None}
            ]
        }
    )


@router.get("/office/{office_id}/domain/{domain}", response_class=HTMLResponse)
async def office_domain_detail(request: Request, office_id: str, domain: str):
    """
    Office + Domain drill-down view (Path B).
    Path B: NPC → Office → Domain → (Assignments)
    Shows assignments for a specific domain within a specific office.
    """
    # Redirect to the domain/office route (same data, different path)
    return RedirectResponse(url=f"/mis/domain/{domain}/office/{office_id}", status_code=302)


# ============================================================
# OFFICE FINANCIAL MIS
# Shows: Value in hand, New value, Target billable, Tentative billable,
#        Invoiced, Received, Expense, Net Revenue
# ============================================================

@router.get("/financial", response_class=HTMLResponse)
async def office_financial_mis(
    request: Request,
    financial_year: Optional[str] = Query(None),
    filter_office: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    """
    Office-level Financial MIS with milestone-based billing projections.
    Shows billable amounts based on target dates vs tentative dates.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Default to current FY if not specified
    if not financial_year:
        today = date.today()
        if today.month >= 4:
            financial_year = f"{today.year}-{str(today.year + 1)[-2:]}"
        else:
            financial_year = f"{today.year - 1}-{str(today.year)[-2:]}"

    fy_start, fy_end = parse_financial_year(financial_year)
    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Build office filter
        office_filter = ""
        office_params = []
        if filter_office:
            office_filter = f"AND a.office_id = {ph}"
            office_params = [filter_office]

        # Build date filter for period
        period_filter = ""
        period_params = []
        if date_from:
            period_filter += f" AND m.target_date >= {ph}"
            period_params.append(date_from)
        if date_to:
            period_filter += f" AND m.target_date <= {ph}"
            period_params.append(date_to)

        # If no date filter, use current FY
        if not date_from and not date_to and fy_start and fy_end:
            period_filter = f" AND m.target_date BETWEEN {ph} AND {ph}"
            period_params = [fy_start.isoformat(), fy_end.isoformat()]

        # Get all offices
        cursor.execute("SELECT office_id, office_name, annual_revenue_target FROM offices ORDER BY office_id")
        offices = {row['office_id']: dict(row) for row in cursor.fetchall()}

        # Initialize office data
        office_financial = {}
        for oid, odata in offices.items():
            office_financial[oid] = {
                'office_id': oid,
                'office_name': odata['office_name'],
                'annual_target': odata['annual_revenue_target'] or 0,
                'total_value_in_hand': 0,  # Total assignment value (active/in-progress)
                'new_value_gained': 0,      # New assignments in period
                'billable_target': 0,       # Billable as per target date
                'billable_tentative': 0,    # Billable as per tentative date
                'invoiced_amount': 0,       # Actual invoice raised
                'payment_received': 0,      # Payment received
                'total_expense': 0,         # Total expenditure
                'net_revenue': 0,           # Payment - Expense
                'assignment_count': 0
            }

        # Get total assignment value in hand (active assignments)
        # Status values: 'Not Started', 'In Progress', 'Completed', 'Delayed', 'Cancelled'
        cursor.execute(f"""
            SELECT a.office_id,
                   COUNT(*) as assignment_count,
                   COALESCE(SUM(a.gross_value), 0) as total_value
            FROM assignments a
            WHERE a.status IN ('Not Started', 'In Progress', 'Delayed')
            {office_filter}
            GROUP BY a.office_id
        """, office_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['total_value_in_hand'] = row['total_value'] or 0
                office_financial[row['office_id']]['assignment_count'] = row['assignment_count'] or 0

        # Get new assignments gained in period
        new_assignment_filter = ""
        new_params = list(office_params)
        if fy_start and fy_end:
            new_assignment_filter = f" AND a.work_order_date BETWEEN {ph} AND {ph}"
            new_params.extend([fy_start.isoformat(), fy_end.isoformat()])

        cursor.execute(f"""
            SELECT a.office_id,
                   COALESCE(SUM(a.gross_value), 0) as new_value
            FROM assignments a
            WHERE 1=1 {office_filter} {new_assignment_filter}
            GROUP BY a.office_id
        """, new_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['new_value_gained'] = row['new_value'] or 0

        # Get billable amounts based on TARGET dates (milestones due in period)
        all_params = office_params + period_params
        cursor.execute(f"""
            SELECT a.office_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100), 0) as billable_amount
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.status IN ('Pending', 'In Progress', 'Completed')
            {office_filter} {period_filter}
            GROUP BY a.office_id
        """, all_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['billable_target'] = row['billable_amount'] or 0

        # Get billable amounts based on TENTATIVE dates
        tentative_filter = period_filter.replace('m.target_date', 'COALESCE(m.tentative_date, m.target_date)')
        cursor.execute(f"""
            SELECT a.office_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100), 0) as billable_amount
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.status IN ('Pending', 'In Progress', 'Completed')
            AND m.tentative_date_status = 'APPROVED'
            {office_filter} {tentative_filter}
            GROUP BY a.office_id
        """, all_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['billable_tentative'] = row['billable_amount'] or 0

        # Get actual invoiced amounts
        cursor.execute(f"""
            SELECT a.office_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100), 0) as invoiced_amount
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.invoice_raised = 1
            {office_filter}
            GROUP BY a.office_id
        """, office_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['invoiced_amount'] = row['invoiced_amount'] or 0

        # Get payment received
        cursor.execute(f"""
            SELECT a.office_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100), 0) as received_amount
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.payment_received = 1
            {office_filter}
            GROUP BY a.office_id
        """, office_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['payment_received'] = row['received_amount'] or 0

        # Get total expenses
        cursor.execute(f"""
            SELECT a.office_id,
                   COALESCE(SUM(a.total_expenditure), 0) as total_expense
            FROM assignments a
            WHERE 1=1 {office_filter}
            GROUP BY a.office_id
        """, office_params)
        for row in cursor.fetchall():
            if row['office_id'] in office_financial:
                office_financial[row['office_id']]['total_expense'] = row['total_expense'] or 0

        # Calculate net revenue for each office
        for oid in office_financial:
            office_financial[oid]['net_revenue'] = (
                office_financial[oid]['payment_received'] - office_financial[oid]['total_expense']
            )

        # Convert to list and filter out empty offices if office filter applied
        financial_data = list(office_financial.values())
        if filter_office:
            financial_data = [d for d in financial_data if d['office_id'] == filter_office]
        else:
            financial_data = [d for d in financial_data if d['assignment_count'] > 0 or d['total_value_in_hand'] > 0]

        # Sort by net revenue
        financial_data = sorted(financial_data, key=lambda x: x['net_revenue'], reverse=True)

        # Calculate totals
        totals = {
            'total_value_in_hand': sum(d['total_value_in_hand'] for d in financial_data),
            'new_value_gained': sum(d['new_value_gained'] for d in financial_data),
            'billable_target': sum(d['billable_target'] for d in financial_data),
            'billable_tentative': sum(d['billable_tentative'] for d in financial_data),
            'invoiced_amount': sum(d['invoiced_amount'] for d in financial_data),
            'payment_received': sum(d['payment_received'] for d in financial_data),
            'total_expense': sum(d['total_expense'] for d in financial_data),
            'net_revenue': sum(d['net_revenue'] for d in financial_data),
            'assignment_count': sum(d['assignment_count'] for d in financial_data)
        }

        # Get office list for filter
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        all_offices = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "mis_financial.html",
        {
            "request": request,
            "user": user,
            "financial_data": financial_data,
            "totals": totals,
            "offices": all_offices,
            "filter_office": filter_office,
            "financial_year": financial_year,
            "financial_years": get_financial_years(),
            "date_from": date_from,
            "date_to": date_to,
            "fy_progress": fy_progress,
            "breadcrumb": [
                {"label": "MIS Dashboard", "url": "/mis"},
                {"label": "Financial MIS", "url": None}
            ]
        }
    )
