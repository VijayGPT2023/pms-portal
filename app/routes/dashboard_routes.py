"""
Dashboard routes: assignment list and main dashboard.
Role-based views: DG, DDG, Group Head, RD Head, Team Leader, Individual.
Three main tabs: Assignments, Training, Development Work. Supports unassigned TL rows.
"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from app.database import get_db, USE_POSTGRES, get_current_fy
from app.dependencies import get_current_user
from app.templates_config import templates
from app.roles import get_user_roles

router = APIRouter()

PH = '%s' if USE_POSTGRES else '?'


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


def get_fy_date_range(fy: str):
    """Convert FY string (e.g. '2025-26') to start/end dates."""
    parts = fy.split('-')
    start_year = int(parts[0])
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


def get_available_fys(cursor):
    """Get list of available financial years from data."""
    current_fy = get_current_fy()
    fys = {current_fy}
    # Also get FYs from invoice_requests
    cursor.execute("SELECT DISTINCT fy_period FROM invoice_requests WHERE fy_period IS NOT NULL")
    for row in cursor.fetchall():
        if row['fy_period']:
            fys.add(row['fy_period'])
    # Get FYs from financial_year_targets
    cursor.execute("SELECT DISTINCT financial_year FROM financial_year_targets WHERE financial_year IS NOT NULL")
    for row in cursor.fetchall():
        if row['financial_year']:
            fys.add(row['financial_year'])
    return sorted(fys, reverse=True)


def get_active_role_info(user: dict):
    """Get detailed info about the user's active role including scope."""
    if not user:
        return None, None, None

    active_role = user.get('active_role', 'OFFICER')
    roles = user.get('roles', [])

    for role in roles:
        if role.get('role_type') == active_role:
            return active_role, role.get('scope_type'), role.get('scope_value')

    return active_role, None, None


def get_offices_for_ddg(cursor, ddg_role: str):
    """Get list of offices that report to a DDG role."""
    cursor.execute(f"""
        SELECT entity_value FROM reporting_hierarchy
        WHERE entity_type = 'OFFICE' AND reports_to_role = {PH}
    """, (ddg_role,))
    return [row['entity_value'] for row in cursor.fetchall()]


def get_groups_for_ddg(cursor, ddg_role: str):
    """Get list of groups that report to a DDG role."""
    cursor.execute(f"""
        SELECT entity_value FROM reporting_hierarchy
        WHERE entity_type = 'GROUP' AND reports_to_role = {PH}
    """, (ddg_role,))
    return [row['entity_value'] for row in cursor.fetchall()]


def build_role_filter(active_role, scope_value, user, role_offices, role_groups):
    """Build WHERE clause and params for role-based filtering on assignments table.
    Returns (where_clause, params, view_title, view_type).
    The where_clause starts with WHERE or AND and assumes table alias 'a'.
    """
    if active_role == 'DG':
        return "WHERE 1=1", [], "Director General View", "npc"

    elif active_role in ('DDG-I', 'DDG-II'):
        all_ids = role_offices + role_groups
        if all_ids:
            placeholders = ','.join([PH for _ in all_ids])
            return f"WHERE a.office_id IN ({placeholders})", list(all_ids), f"{active_role} View", "ddg"
        return "WHERE 1=0", [], f"{active_role} View", "ddg"

    elif active_role == 'GROUP_HEAD' and scope_value:
        return f"WHERE a.office_id = {PH}", [scope_value], f"Group Head ({scope_value}) View", "group"

    elif active_role == 'RD_HEAD' and scope_value:
        return f"WHERE a.office_id = {PH}", [scope_value], f"RD Head ({scope_value}) View", "office"

    elif active_role == 'TEAM_LEADER':
        return f"WHERE a.team_leader_officer_id = {PH}", [user['officer_id']], "Team Leader View", "team_leader"

    elif active_role == 'ADMIN':
        return "WHERE 1=1", [], "Administrator View", "npc"

    else:
        # OFFICER (Individual) - handled differently per tab
        return "INDIVIDUAL", [user['officer_id']], "My Dashboard", "individual"


def get_tab_counts(cursor, role_where, role_params, view_type, user):
    """Get count of items per tab for badges."""
    counts = {'assignments': 0, 'training': 0, 'total_real_revenue': 0, 'development': 0, 'total_revenue': 0}

    if view_type == 'individual':
        officer_id = user['officer_id']
        # Assignments where user has revenue share
        cursor.execute(f"""
            SELECT
                SUM(CASE WHEN a.type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as assignments,
                SUM(CASE WHEN a.type = 'TRAINING' THEN 1 ELSE 0 END) as training
            FROM assignments a
            JOIN revenue_shares rs ON a.id = rs.assignment_id
            WHERE rs.officer_id = {PH}
        """, (officer_id,))
        row = cursor.fetchone()
        if row:
            counts['assignments'] = row['assignments'] or 0
            counts['training'] = row['training'] or 0

        # Development work
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM non_revenue_suggestions
            WHERE officer_id = {PH}
        """, (officer_id,))
        row = cursor.fetchone()
        counts['development'] = row['cnt'] if row else 0
    else:
        # Count from assignments table by type
        cursor.execute(f"""
            SELECT
                SUM(CASE WHEN a.type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as assignments,
                SUM(CASE WHEN a.type = 'TRAINING' THEN 1 ELSE 0 END) as training
            FROM assignments a
            {role_where}
        """, role_params)
        row = cursor.fetchone()
        if row:
            counts['assignments'] = row['assignments'] or 0
            counts['training'] = row['training'] or 0

        # Development work (non_revenue_suggestions)
        if view_type == 'npc':
            cursor.execute("SELECT COUNT(*) as cnt FROM non_revenue_suggestions")
        elif view_type == 'ddg':
            all_ids = role_params  # These are office_ids for DDG
            if all_ids:
                placeholders = ','.join([PH for _ in all_ids])
                cursor.execute(f"SELECT COUNT(*) as cnt FROM non_revenue_suggestions WHERE office_id IN ({placeholders})", all_ids)
            else:
                cursor.execute("SELECT 0 as cnt")
        elif view_type in ('group', 'office'):
            cursor.execute(f"SELECT COUNT(*) as cnt FROM non_revenue_suggestions WHERE office_id = {PH}", (role_params[0] if role_params else '',))
        elif view_type == 'team_leader':
            cursor.execute(f"SELECT COUNT(*) as cnt FROM non_revenue_suggestions WHERE officer_id = {PH}", (user['officer_id'],))
        else:
            cursor.execute("SELECT 0 as cnt")
        row = cursor.fetchone()
        counts['development'] = row['cnt'] if row else 0

    counts['total_real_revenue'] = counts['assignments'] + counts['training']
    counts['total_revenue'] = counts['assignments'] + counts['training'] + counts['development']
    return counts


def get_tab_items(cursor, active_tab, role_where, role_params, view_type, user, filter_office, filter_status):
    """Get items for the active tab."""
    items = []

    if active_tab == 'development':
        return get_development_items(cursor, role_where, role_params, view_type, user, filter_office, filter_status)

    # Assignments or Training tab - query from assignments table
    type_filter = 'ASSIGNMENT' if active_tab == 'assignments' else 'TRAINING'

    if view_type == 'individual':
        officer_id = user['officer_id']
        query = f"""
            SELECT DISTINCT
                a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                a.status, a.gross_value, a.invoice_amount, a.amount_received,
                a.total_revenue, a.details_filled, a.total_expenditure, a.surplus_deficit,
                a.target_date, a.start_date,
                rs.share_percent, rs.share_amount
            FROM assignments a
            JOIN revenue_shares rs ON a.id = rs.assignment_id
            WHERE rs.officer_id = {PH} AND a.type = {PH}
        """
        params = [officer_id, type_filter]
    else:
        query = f"""
            SELECT
                a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                a.status, a.gross_value, a.invoice_amount, a.amount_received,
                a.total_revenue, a.details_filled, a.team_leader_officer_id,
                a.total_expenditure, a.surplus_deficit, a.target_date, a.start_date, a.domain,
                (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
            FROM assignments a
            {role_where} AND a.type = {PH}
        """
        params = list(role_params) + [type_filter]

    if filter_office and view_type in ('npc', 'ddg'):
        query += f" AND a.office_id = {PH}"
        params.append(filter_office)
    if filter_status:
        query += f" AND a.status = {PH}"
        params.append(filter_status)

    query += " ORDER BY a.assignment_no DESC LIMIT 100"
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_development_items(cursor, role_where, role_params, view_type, user, filter_office, filter_status):
    """Get development work items from non_revenue_suggestions."""
    if view_type == 'individual':
        query = f"""
            SELECT s.*, o.name as officer_name
            FROM non_revenue_suggestions s
            LEFT JOIN officers o ON s.officer_id = o.officer_id
            WHERE s.officer_id = {PH}
        """
        params = [user['officer_id']]
    elif view_type == 'npc':
        query = """
            SELECT s.*, o.name as officer_name
            FROM non_revenue_suggestions s
            LEFT JOIN officers o ON s.officer_id = o.officer_id
            WHERE 1=1
        """
        params = []
    elif view_type == 'ddg':
        all_ids = role_params
        if all_ids:
            placeholders = ','.join([PH for _ in all_ids])
            query = f"""
                SELECT s.*, o.name as officer_name
                FROM non_revenue_suggestions s
                LEFT JOIN officers o ON s.officer_id = o.officer_id
                WHERE s.office_id IN ({placeholders})
            """
            params = list(all_ids)
        else:
            return []
    elif view_type in ('group', 'office'):
        query = f"""
            SELECT s.*, o.name as officer_name
            FROM non_revenue_suggestions s
            LEFT JOIN officers o ON s.officer_id = o.officer_id
            WHERE s.office_id = {PH}
        """
        params = [role_params[0] if role_params else '']
    elif view_type == 'team_leader':
        query = f"""
            SELECT s.*, o.name as officer_name
            FROM non_revenue_suggestions s
            LEFT JOIN officers o ON s.officer_id = o.officer_id
            WHERE s.officer_id = {PH}
        """
        params = [user['officer_id']]
    else:
        return []

    if filter_office:
        query += f" AND s.office_id = {PH}"
        params.append(filter_office)
    if filter_status:
        query += f" AND s.status = {PH}"
        params.append(filter_status)

    query += " ORDER BY s.created_at DESC LIMIT 100"
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_tab_summary(cursor, active_tab, role_where, role_params, view_type, user, fy):
    """Get 10 summary card values for a tab.

    Returns: active_count, targeted_value, tentative_value, completed_value,
             billed_fy, to_be_billed_fy, payment_received, expenses_fy,
             net_value, surplus_deficit
    """
    if active_tab == 'development':
        return get_development_summary(cursor, role_where, role_params, view_type, user)
    if active_tab == 'total_real_revenue':
        return get_combined_summary(cursor, ['assignments', 'training'], role_where, role_params, view_type, user, fy)
    if active_tab == 'total_revenue':
        return get_combined_summary(cursor, ['assignments', 'training', 'development'], role_where, role_params, view_type, user, fy)

    type_filter = 'ASSIGNMENT' if active_tab == 'assignments' else 'TRAINING'
    is_training = (active_tab == 'training')
    fy_start, fy_end = get_fy_date_range(fy)

    summary = {
        'active_count': 0,
        'targeted_value': 0,
        'tentative_value': 0,
        'completed_value': 0,
        'billed_fy': 0,
        'to_be_billed_fy': 0,
        'payment_received': 0,
        'expenses_fy': 0,
        'net_value': 0,
        'surplus_deficit': 0,
    }

    if view_type == 'individual':
        officer_id = user['officer_id']
        # Active count
        cursor.execute(f"""
            SELECT COUNT(DISTINCT a.id) as cnt
            FROM assignments a
            JOIN revenue_shares rs ON a.id = rs.assignment_id
            WHERE rs.officer_id = {PH} AND a.type = {PH}
            AND a.status IN ('In Progress', 'Not Started', 'Ongoing')
        """, (officer_id, type_filter))
        row = cursor.fetchone()
        summary['active_count'] = (row['cnt'] or 0) if row else 0

        # Targeted / Tentative / Completed
        if is_training:
            cursor.execute(f"""
                SELECT
                    COALESCE(SUM(a.target_participants * a.fee_per_participant), 0) as targeted,
                    COALESCE(SUM(a.tentative_participants * a.fee_per_participant), 0) as tentative,
                    COALESCE(SUM(a.actual_participants * a.fee_per_participant), 0) as completed
                FROM assignments a
                JOIN revenue_shares rs ON a.id = rs.assignment_id
                WHERE rs.officer_id = {PH} AND a.type = {PH}
            """, (officer_id, type_filter))
        else:
            cursor.execute(f"""
                SELECT
                    COALESCE(SUM(a.gross_value), 0) as targeted,
                    COALESCE(SUM(
                        CASE WHEN sub.tent_pct IS NOT NULL THEN a.gross_value * sub.tent_pct / 100.0
                             ELSE a.gross_value END
                    ), 0) as tentative,
                    COALESCE(SUM(
                        CASE WHEN sub.comp_pct IS NOT NULL THEN a.gross_value * sub.comp_pct / 100.0
                             ELSE 0 END
                    ), 0) as completed
                FROM assignments a
                JOIN revenue_shares rs ON a.id = rs.assignment_id
                LEFT JOIN (
                    SELECT m.assignment_id,
                        SUM(CASE WHEN m.tentative_date IS NOT NULL OR m.status IN ('Completed','In Progress') THEN m.revenue_percent ELSE 0 END) as tent_pct,
                        SUM(CASE WHEN m.status = 'Completed' THEN m.revenue_percent ELSE 0 END) as comp_pct
                    FROM milestones m GROUP BY m.assignment_id
                ) sub ON a.id = sub.assignment_id
                WHERE rs.officer_id = {PH} AND a.type = {PH}
            """, (officer_id, type_filter))
        row = cursor.fetchone()
        if row:
            summary['targeted_value'] = row['targeted'] or 0
            summary['tentative_value'] = row['tentative'] or 0
            summary['completed_value'] = row['completed'] or 0

        # Billed in selected FY
        cursor.execute(f"""
            SELECT COALESCE(SUM(ir.invoice_amount), 0) as amt
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN revenue_shares rs ON a.id = rs.assignment_id
            WHERE rs.officer_id = {PH} AND a.type = {PH}
            AND ir.fy_period = {PH}
        """, (officer_id, type_filter, fy))
        row = cursor.fetchone()
        summary['billed_fy'] = row['amt'] if row else 0

        # Payment received in FY
        cursor.execute(f"""
            SELECT COALESCE(SUM(pr.amount_received), 0) as amt
            FROM payment_receipts pr
            JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN revenue_shares rs ON a.id = rs.assignment_id
            WHERE rs.officer_id = {PH} AND a.type = {PH} AND pr.fy_period = {PH}
        """, (officer_id, type_filter, fy))
        row = cursor.fetchone()
        summary['payment_received'] = row['amt'] if row else 0

        # Expenses in selected FY
        cursor.execute(f"""
            SELECT COALESCE(SUM(ee.amount), 0) as amt
            FROM expenditure_entries ee
            JOIN assignments a ON ee.assignment_id = a.id
            JOIN revenue_shares rs ON a.id = rs.assignment_id
            WHERE rs.officer_id = {PH} AND a.type = {PH} AND ee.fy_period = {PH}
        """, (officer_id, type_filter, fy))
        row = cursor.fetchone()
        summary['expenses_fy'] = row['amt'] if row else 0

    else:
        # Non-individual views
        # Active count
        cursor.execute(f"""
            SELECT COUNT(*) as cnt
            FROM assignments a
            {role_where} AND a.type = {PH}
            AND a.status IN ('In Progress', 'Not Started', 'Ongoing')
        """, list(role_params) + [type_filter])
        row = cursor.fetchone()
        summary['active_count'] = (row['cnt'] or 0) if row else 0

        # Targeted / Tentative / Completed
        if is_training:
            cursor.execute(f"""
                SELECT
                    COALESCE(SUM(a.target_participants * a.fee_per_participant), 0) as targeted,
                    COALESCE(SUM(a.tentative_participants * a.fee_per_participant), 0) as tentative,
                    COALESCE(SUM(a.actual_participants * a.fee_per_participant), 0) as completed
                FROM assignments a
                {role_where} AND a.type = {PH}
            """, list(role_params) + [type_filter])
        else:
            cursor.execute(f"""
                SELECT
                    COALESCE(SUM(a.gross_value), 0) as targeted,
                    COALESCE(SUM(
                        CASE WHEN sub.tent_pct IS NOT NULL THEN a.gross_value * sub.tent_pct / 100.0
                             ELSE a.gross_value END
                    ), 0) as tentative,
                    COALESCE(SUM(
                        CASE WHEN sub.comp_pct IS NOT NULL THEN a.gross_value * sub.comp_pct / 100.0
                             ELSE 0 END
                    ), 0) as completed
                FROM assignments a
                LEFT JOIN (
                    SELECT m.assignment_id,
                        SUM(CASE WHEN m.tentative_date IS NOT NULL OR m.status IN ('Completed','In Progress') THEN m.revenue_percent ELSE 0 END) as tent_pct,
                        SUM(CASE WHEN m.status = 'Completed' THEN m.revenue_percent ELSE 0 END) as comp_pct
                    FROM milestones m GROUP BY m.assignment_id
                ) sub ON a.id = sub.assignment_id
                {role_where} AND a.type = {PH}
            """, list(role_params) + [type_filter])
        row = cursor.fetchone()
        if row:
            summary['targeted_value'] = row['targeted'] or 0
            summary['tentative_value'] = row['tentative'] or 0
            summary['completed_value'] = row['completed'] or 0

        # Billed in selected FY
        cursor.execute(f"""
            SELECT COALESCE(SUM(ir.invoice_amount), 0) as amt
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            {role_where} AND a.type = {PH}
            AND ir.fy_period = {PH}
        """, list(role_params) + [type_filter, fy])
        row = cursor.fetchone()
        summary['billed_fy'] = row['amt'] if row else 0

        # Payment received in FY
        cursor.execute(f"""
            SELECT COALESCE(SUM(pr.amount_received), 0) as amt
            FROM payment_receipts pr
            JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
            JOIN assignments a ON ir.assignment_id = a.id
            {role_where} AND a.type = {PH} AND pr.fy_period = {PH}
        """, list(role_params) + [type_filter, fy])
        row = cursor.fetchone()
        summary['payment_received'] = row['amt'] if row else 0

        # Expenses in selected FY
        cursor.execute(f"""
            SELECT COALESCE(SUM(ee.amount), 0) as amt
            FROM expenditure_entries ee
            JOIN assignments a ON ee.assignment_id = a.id
            {role_where} AND a.type = {PH} AND ee.fy_period = {PH}
        """, list(role_params) + [type_filter, fy])
        row = cursor.fetchone()
        summary['expenses_fy'] = row['amt'] if row else 0

    # To Be Billed: milestone-based (milestones due in FY where invoice not raised)
    if is_training:
        # Training: no milestone-based to_be_billed, use completed - billed
        summary['to_be_billed_fy'] = max(summary['completed_value'] - summary['billed_fy'], 0)
    else:
        if view_type == 'individual':
            officer_id = user['officer_id']
            cursor.execute(f"""
                SELECT COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0), 0) as amt
                FROM milestones m
                JOIN assignments a ON m.assignment_id = a.id
                JOIN revenue_shares rs ON a.id = rs.assignment_id
                WHERE rs.officer_id = {PH} AND a.type = {PH}
                AND m.target_date >= {PH} AND m.target_date <= {PH}
                AND m.invoice_raised = 0
            """, (officer_id, type_filter, fy_start, fy_end))
        else:
            cursor.execute(f"""
                SELECT COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0), 0) as amt
                FROM milestones m
                JOIN assignments a ON m.assignment_id = a.id
                {role_where} AND a.type = {PH}
                AND m.target_date >= {PH} AND m.target_date <= {PH}
                AND m.invoice_raised = 0
            """, list(role_params) + [type_filter, fy_start, fy_end])
        row = cursor.fetchone()
        summary['to_be_billed_fy'] = row['amt'] if row else 0

    summary['net_value'] = summary['completed_value'] - summary['expenses_fy']
    summary['surplus_deficit'] = summary['payment_received'] - summary['expenses_fy']
    return summary


def get_development_summary(cursor, role_where, role_params, view_type, user):
    """Get 10 summary cards for Development Work tab (notional values, no billing)."""
    summary = {
        'active_count': 0,
        'targeted_value': 0,
        'tentative_value': 0,
        'completed_value': 0,
        'billed_fy': 0,
        'to_be_billed_fy': 0,
        'payment_received': 0,
        'expenses_fy': 0,
        'net_value': 0,
        'surplus_deficit': 0,
    }

    if view_type == 'individual':
        officer_id = user['officer_id']
        base_where = f"WHERE s.officer_id = {PH}"
        base_params = [officer_id]
    elif view_type == 'npc':
        base_where = "WHERE 1=1"
        base_params = []
    elif view_type == 'ddg':
        all_ids = role_params
        if all_ids:
            placeholders = ','.join([PH for _ in all_ids])
            base_where = f"WHERE s.office_id IN ({placeholders})"
            base_params = list(all_ids)
        else:
            return summary
    elif view_type in ('group', 'office'):
        base_where = f"WHERE s.office_id = {PH}"
        base_params = [role_params[0] if role_params else '']
    elif view_type == 'team_leader':
        base_where = f"WHERE s.officer_id = {PH}"
        base_params = [user['officer_id']]
    else:
        return summary

    # Active count
    cursor.execute(f"""
        SELECT COUNT(*) as cnt
        FROM non_revenue_suggestions s
        {base_where} AND s.status IN ('APPROVED', 'IN_PROGRESS')
    """, base_params)
    row = cursor.fetchone()
    summary['active_count'] = (row['cnt'] or 0) if row else 0

    # Targeted = all notional value (excluding rejected/dropped)
    cursor.execute(f"""
        SELECT COALESCE(SUM(s.notional_value), 0) as val
        FROM non_revenue_suggestions s
        {base_where} AND s.status NOT IN ('REJECTED', 'DROPPED')
    """, base_params)
    row = cursor.fetchone()
    summary['targeted_value'] = row['val'] if row else 0
    summary['tentative_value'] = summary['targeted_value']  # dev has no tentative concept

    # Completed = notional earned
    cursor.execute(f"""
        SELECT COALESCE(SUM(s.notional_value), 0) as val
        FROM non_revenue_suggestions s
        {base_where} AND s.status = 'COMPLETED'
    """, base_params)
    row = cursor.fetchone()
    summary['completed_value'] = row['val'] if row else 0

    # Development has no billing, payment, or expenditure
    summary['net_value'] = summary['completed_value']
    return summary


def get_combined_summary(cursor, tabs_to_combine, role_where, role_params, view_type, user, fy):
    """Sum metrics across multiple tabs (for Total Real Revenue / Total Revenue)."""
    keys = ['active_count', 'targeted_value', 'tentative_value', 'completed_value',
            'billed_fy', 'to_be_billed_fy', 'payment_received', 'expenses_fy',
            'net_value', 'surplus_deficit']
    combined = {k: 0 for k in keys}
    for tab in tabs_to_combine:
        s = get_tab_summary(cursor, tab, role_where, role_params, view_type, user, fy)
        for k in keys:
            combined[k] += s.get(k, 0)
    return combined


# ── Hierarchical sub-view aggregation functions ──────────────────────

def get_entity_rows(cursor, office_ids, type_filter, fy):
    """For DDG/DG: Return one row per office/group with aggregated financial metrics.
    Uses CTEs to avoid N+1 queries. Returns 10-metric rows."""
    if not office_ids:
        return []

    is_training = (type_filter == 'TRAINING')
    fy_start, fy_end = get_fy_date_range(fy)
    n = len(office_ids)
    ph_list = ','.join([PH] * n)

    # Targeted/Completed CTE differs by type
    if is_training:
        targeted_cte = f"""
        targeted_by_office AS (
            SELECT a.office_id,
                   COALESCE(SUM(a.target_participants * a.fee_per_participant), 0) as targeted,
                   COALESCE(SUM(a.tentative_participants * a.fee_per_participant), 0) as tentative,
                   COALESCE(SUM(a.actual_participants * a.fee_per_participant), 0) as completed
            FROM assignments a
            WHERE a.office_id IN ({ph_list}) AND a.type = {PH}
            GROUP BY a.office_id
        )"""
        targeted_params = list(office_ids) + [type_filter]
    else:
        targeted_cte = f"""
        targeted_by_office AS (
            SELECT a.office_id,
                   COALESCE(SUM(a.gross_value), 0) as targeted,
                   COALESCE(SUM(a.gross_value), 0) as tentative,
                   COALESCE(SUM(
                       CASE WHEN sub.comp_pct IS NOT NULL THEN a.gross_value * sub.comp_pct / 100.0 ELSE 0 END
                   ), 0) as completed
            FROM assignments a
            LEFT JOIN (
                SELECT m.assignment_id,
                    SUM(CASE WHEN m.status = 'Completed' THEN m.revenue_percent ELSE 0 END) as comp_pct
                FROM milestones m GROUP BY m.assignment_id
            ) sub ON a.id = sub.assignment_id
            WHERE a.office_id IN ({ph_list}) AND a.type = {PH}
            GROUP BY a.office_id
        )"""
        targeted_params = list(office_ids) + [type_filter]

    query = f"""
        WITH active_by_office AS (
            SELECT a.office_id,
                   COUNT(*) as active_count
            FROM assignments a
            WHERE a.office_id IN ({ph_list}) AND a.type = {PH}
              AND a.status IN ('In Progress', 'Not Started', 'Ongoing')
            GROUP BY a.office_id
        ),
        {targeted_cte},
        billed_by_office AS (
            SELECT a.office_id,
                   COALESCE(SUM(ir.invoice_amount), 0) as billed
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE a.office_id IN ({ph_list}) AND a.type = {PH} AND ir.fy_period = {PH}
            GROUP BY a.office_id
        ),
        received_by_office AS (
            SELECT a.office_id,
                   COALESCE(SUM(pr.amount_received), 0) as received
            FROM payment_receipts pr
            JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE a.office_id IN ({ph_list}) AND a.type = {PH} AND pr.fy_period = {PH}
            GROUP BY a.office_id
        ),
        expenses_by_office AS (
            SELECT a.office_id,
                   COALESCE(SUM(ee.amount), 0) as expenses
            FROM expenditure_entries ee
            JOIN assignments a ON ee.assignment_id = a.id
            WHERE a.office_id IN ({ph_list}) AND a.type = {PH} AND ee.fy_period = {PH}
            GROUP BY a.office_id
        )
        SELECT
            o.office_id, o.office_name,
            COALESCE(act.active_count, 0) as active_count,
            COALESCE(tgt.targeted, 0) as targeted_value,
            COALESCE(tgt.tentative, 0) as tentative_value,
            COALESCE(tgt.completed, 0) as completed_value,
            COALESCE(bil.billed, 0) as billed_fy,
            COALESCE(tgt.completed, 0) - COALESCE(bil.billed, 0) as to_be_billed,
            COALESCE(rec.received, 0) as payment_received,
            COALESCE(exp.expenses, 0) as expenses_fy,
            COALESCE(tgt.completed, 0) - COALESCE(exp.expenses, 0) as net_value,
            COALESCE(rec.received, 0) - COALESCE(exp.expenses, 0) as surplus_deficit
        FROM offices o
        LEFT JOIN active_by_office act ON o.office_id = act.office_id
        LEFT JOIN targeted_by_office tgt ON o.office_id = tgt.office_id
        LEFT JOIN billed_by_office bil ON o.office_id = bil.office_id
        LEFT JOIN received_by_office rec ON o.office_id = rec.office_id
        LEFT JOIN expenses_by_office exp ON o.office_id = exp.office_id
        WHERE o.office_id IN ({ph_list})
        ORDER BY COALESCE(tgt.targeted, 0) DESC
    """
    params = (
        list(office_ids) + [type_filter] +          # active CTE
        targeted_params +                            # targeted CTE
        list(office_ids) + [type_filter, fy] +      # billed CTE
        list(office_ids) + [type_filter, fy] +      # received CTE
        list(office_ids) + [type_filter, fy] +      # expenses CTE
        list(office_ids)                             # final WHERE
    )

    try:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def get_team_leader_rows(cursor, office_id, type_filter, fy):
    """For a given office: Return one row per team leader with 10-metric aggregation.
    Includes an 'Unassigned' row for items without a team leader."""
    is_training = (type_filter == 'TRAINING')
    fy_start, fy_end = get_fy_date_range(fy)

    if is_training:
        targeted_cte = f"""
        tl_targeted AS (
            SELECT a.team_leader_officer_id as tl_id,
                   COALESCE(SUM(a.target_participants * a.fee_per_participant), 0) as targeted,
                   COALESCE(SUM(a.tentative_participants * a.fee_per_participant), 0) as tentative,
                   COALESCE(SUM(a.actual_participants * a.fee_per_participant), 0) as completed
            FROM assignments a
            WHERE a.office_id = {PH} AND a.type = {PH}
            GROUP BY a.team_leader_officer_id
        )"""
    else:
        targeted_cte = f"""
        tl_targeted AS (
            SELECT a.team_leader_officer_id as tl_id,
                   COALESCE(SUM(a.gross_value), 0) as targeted,
                   COALESCE(SUM(a.gross_value), 0) as tentative,
                   COALESCE(SUM(
                       CASE WHEN sub.comp_pct IS NOT NULL THEN a.gross_value * sub.comp_pct / 100.0 ELSE 0 END
                   ), 0) as completed
            FROM assignments a
            LEFT JOIN (
                SELECT m.assignment_id,
                    SUM(CASE WHEN m.status = 'Completed' THEN m.revenue_percent ELSE 0 END) as comp_pct
                FROM milestones m GROUP BY m.assignment_id
            ) sub ON a.id = sub.assignment_id
            WHERE a.office_id = {PH} AND a.type = {PH}
            GROUP BY a.team_leader_officer_id
        )"""

    query = f"""
        WITH tl_active AS (
            SELECT a.team_leader_officer_id as tl_id,
                   COUNT(*) as active_count
            FROM assignments a
            WHERE a.office_id = {PH} AND a.type = {PH}
              AND a.status IN ('In Progress', 'Not Started', 'Ongoing')
            GROUP BY a.team_leader_officer_id
        ),
        {targeted_cte},
        tl_billed AS (
            SELECT a.team_leader_officer_id as tl_id,
                   COALESCE(SUM(ir.invoice_amount), 0) as billed
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE a.office_id = {PH} AND a.type = {PH} AND ir.fy_period = {PH}
            GROUP BY a.team_leader_officer_id
        ),
        tl_received AS (
            SELECT a.team_leader_officer_id as tl_id,
                   COALESCE(SUM(pr.amount_received), 0) as received
            FROM payment_receipts pr
            JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE a.office_id = {PH} AND a.type = {PH} AND pr.fy_period = {PH}
            GROUP BY a.team_leader_officer_id
        ),
        tl_expenses AS (
            SELECT a.team_leader_officer_id as tl_id,
                   COALESCE(SUM(ee.amount), 0) as expenses
            FROM expenditure_entries ee
            JOIN assignments a ON ee.assignment_id = a.id
            WHERE a.office_id = {PH} AND a.type = {PH} AND ee.fy_period = {PH}
            GROUP BY a.team_leader_officer_id
        )
        SELECT
            o.officer_id, o.name as tl_name, o.designation,
            COALESCE(act.active_count, 0) as active_count,
            COALESCE(tgt.targeted, 0) as targeted_value,
            COALESCE(tgt.tentative, 0) as tentative_value,
            COALESCE(tgt.completed, 0) as completed_value,
            COALESCE(bil.billed, 0) as billed_fy,
            COALESCE(tgt.completed, 0) - COALESCE(bil.billed, 0) as to_be_billed,
            COALESCE(rec.received, 0) as payment_received,
            COALESCE(exp.expenses, 0) as expenses_fy,
            COALESCE(tgt.completed, 0) - COALESCE(exp.expenses, 0) as net_value,
            COALESCE(rec.received, 0) - COALESCE(exp.expenses, 0) as surplus_deficit
        FROM officers o
        JOIN tl_targeted tgt ON o.officer_id = tgt.tl_id
        LEFT JOIN tl_active act ON o.officer_id = act.tl_id
        LEFT JOIN tl_billed bil ON o.officer_id = bil.tl_id
        LEFT JOIN tl_received rec ON o.officer_id = rec.tl_id
        LEFT JOIN tl_expenses exp ON o.officer_id = exp.tl_id
        WHERE tgt.tl_id IS NOT NULL
        ORDER BY COALESCE(tgt.targeted, 0) DESC
    """
    params = (
        [office_id, type_filter] +         # active
        [office_id, type_filter] +         # targeted
        [office_id, type_filter, fy] +     # billed
        [office_id, type_filter, fy] +     # received
        [office_id, type_filter, fy]       # expenses
    )

    try:
        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
    except Exception:
        rows = []

    # Check for unassigned items (team_leader_officer_id IS NULL)
    try:
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM assignments a
            WHERE a.office_id = {PH} AND a.type = {PH}
              AND a.status IN ('In Progress', 'Not Started', 'Ongoing')
              AND a.team_leader_officer_id IS NULL
        """, [office_id, type_filter])
        urow = cursor.fetchone()
        if urow and (urow['cnt'] or 0) > 0:
            rows.append({
                'officer_id': '__unassigned__',
                'tl_name': 'Unassigned (No TL)',
                'designation': '-',
                'active_count': urow['cnt'] or 0,
                'targeted_value': 0, 'tentative_value': 0, 'completed_value': 0,
                'billed_fy': 0, 'to_be_billed': 0,
                'payment_received': 0, 'expenses_fy': 0,
                'net_value': 0, 'surplus_deficit': 0,
            })
    except Exception:
        pass

    return rows


def get_officer_rows(cursor, tl_officer_id, type_filter, fy):
    """For a given TL: Return one row per officer with milestone-based metrics.

    Returns per officer: annual_target, targeted_value, tentative_value,
    completed_value, revenue_earned (80/20 model).
    """
    fy_start, fy_end = get_fy_date_range(fy)

    query = f"""
        WITH tl_assignments AS (
            SELECT a.id, a.gross_value
            FROM assignments a
            WHERE a.team_leader_officer_id = {PH} AND a.type = {PH}
        ),
        all_officers AS (
            SELECT DISTINCT rs.officer_id
            FROM revenue_shares rs
            WHERE rs.assignment_id IN (SELECT id FROM tl_assignments)
        ),
        officer_targeted AS (
            SELECT rs.officer_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0 * rs.share_percent / 100.0), 0) as targeted
            FROM revenue_shares rs
            JOIN tl_assignments a ON rs.assignment_id = a.id
            JOIN milestones m ON m.assignment_id = a.id
            WHERE m.target_date >= {PH} AND m.target_date <= {PH}
            GROUP BY rs.officer_id
        ),
        officer_tentative AS (
            SELECT rs.officer_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0 * rs.share_percent / 100.0), 0) as tentative
            FROM revenue_shares rs
            JOIN tl_assignments a ON rs.assignment_id = a.id
            JOIN milestones m ON m.assignment_id = a.id
            WHERE (m.tentative_date >= {PH} AND m.tentative_date <= {PH})
               OR (m.actual_completion_date >= {PH} AND m.actual_completion_date <= {PH})
            GROUP BY rs.officer_id
        ),
        officer_completed AS (
            SELECT rs.officer_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0 * rs.share_percent / 100.0), 0) as completed
            FROM revenue_shares rs
            JOIN tl_assignments a ON rs.assignment_id = a.id
            JOIN milestones m ON m.assignment_id = a.id
            WHERE m.actual_completion_date >= {PH} AND m.actual_completion_date <= {PH}
            GROUP BY rs.officer_id
        ),
        rev_100 AS (
            SELECT rs.officer_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0 * rs.share_percent / 100.0), 0) as earned
            FROM revenue_shares rs
            JOIN tl_assignments a ON rs.assignment_id = a.id
            JOIN milestones m ON m.assignment_id = a.id
            WHERE m.status = 'Completed'
              AND m.payment_received = 1
              AND m.payment_received_date >= {PH} AND m.payment_received_date <= {PH}
            GROUP BY rs.officer_id
        ),
        rev_80 AS (
            SELECT rs.officer_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0 * rs.share_percent / 100.0 * 0.8), 0) as earned
            FROM revenue_shares rs
            JOIN tl_assignments a ON rs.assignment_id = a.id
            JOIN milestones m ON m.assignment_id = a.id
            WHERE m.status = 'Completed'
              AND m.actual_completion_date >= {PH} AND m.actual_completion_date <= {PH}
              AND m.payment_received = 0
            GROUP BY rs.officer_id
        ),
        rev_20 AS (
            SELECT rs.officer_id,
                   COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0 * rs.share_percent / 100.0 * 0.2), 0) as earned
            FROM revenue_shares rs
            JOIN tl_assignments a ON rs.assignment_id = a.id
            JOIN milestones m ON m.assignment_id = a.id
            WHERE m.payment_received = 1
              AND m.payment_received_date >= {PH} AND m.payment_received_date <= {PH}
              AND m.invoice_raised = 1
              AND m.invoice_raised_date < {PH}
            GROUP BY rs.officer_id
        )
        SELECT
            o.officer_id, o.name, o.designation, o.office_id as officer_office,
            COALESCE(o.annual_target, 60.0) as annual_target,
            COALESCE(tgt.targeted, 0) as targeted_value,
            COALESCE(tent.tentative, 0) as tentative_value,
            COALESCE(comp.completed, 0) as completed_value,
            COALESCE(r100.earned, 0) + COALESCE(r80.earned, 0) + COALESCE(r20.earned, 0) as revenue_earned
        FROM officers o
        JOIN all_officers ao ON o.officer_id = ao.officer_id
        LEFT JOIN officer_targeted tgt ON o.officer_id = tgt.officer_id
        LEFT JOIN officer_tentative tent ON o.officer_id = tent.officer_id
        LEFT JOIN officer_completed comp ON o.officer_id = comp.officer_id
        LEFT JOIN rev_100 r100 ON o.officer_id = r100.officer_id
        LEFT JOIN rev_80 r80 ON o.officer_id = r80.officer_id
        LEFT JOIN rev_20 r20 ON o.officer_id = r20.officer_id
        ORDER BY COALESCE(tgt.targeted, 0) DESC
    """
    params = [
        tl_officer_id, type_filter,            # tl_assignments
        fy_start, fy_end,                      # officer_targeted
        fy_start, fy_end, fy_start, fy_end,    # officer_tentative (tentative OR actual)
        fy_start, fy_end,                      # officer_completed
        fy_start, fy_end,                      # rev_100
        fy_start, fy_end,                      # rev_80
        fy_start, fy_end, fy_start,            # rev_20 (payment in period, invoice before period)
    ]

    try:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def get_development_officer_rows(cursor, tl_officer_id, fy):
    """For development tab: Return officer rows from non_revenue_suggestions.
    Development items link by officer_id, scoped to TL's office(s)."""
    query = f"""
        SELECT
            o.officer_id, o.name, o.designation,
            o.office_id as officer_office,
            0.0 as annual_target,
            COALESCE(SUM(CASE WHEN nrs.status NOT IN ('DROPPED','REJECTED') THEN nrs.notional_value ELSE 0 END), 0) as targeted_value,
            COALESCE(SUM(CASE WHEN nrs.status NOT IN ('DROPPED','REJECTED') THEN nrs.notional_value ELSE 0 END), 0) as tentative_value,
            COALESCE(SUM(CASE WHEN nrs.status = 'COMPLETED' THEN nrs.notional_value ELSE 0 END), 0) as completed_value,
            COALESCE(SUM(CASE WHEN nrs.status = 'COMPLETED' THEN nrs.notional_value ELSE 0 END), 0) as revenue_earned
        FROM officers o
        JOIN non_revenue_suggestions nrs ON o.officer_id = nrs.officer_id
        WHERE nrs.office_id IN (
            SELECT DISTINCT a.office_id FROM assignments a
            WHERE a.team_leader_officer_id = {PH}
        )
        GROUP BY o.officer_id, o.name, o.designation, o.office_id
        ORDER BY targeted_value DESC
    """
    try:
        cursor.execute(query, [tl_officer_id])
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def _merge_sub_rows(rows_list, key_field):
    """Merge multiple lists of sub_rows by key_field, summing numeric values."""
    merged = {}
    for rows in rows_list:
        for row in rows:
            k = row.get(key_field)
            if k not in merged:
                merged[k] = dict(row)
            else:
                for field, val in row.items():
                    if isinstance(val, (int, float)) and field != key_field:
                        merged[k][field] = merged[k].get(field, 0) + val
    return list(merged.values())


def get_combined_entity_rows(cursor, office_ids, type_filters, fy):
    """Merge entity rows from multiple type_filters."""
    all_rows = [get_entity_rows(cursor, office_ids, tf, fy) for tf in type_filters]
    return _merge_sub_rows(all_rows, 'office_id')


def get_combined_tl_rows(cursor, office_id, type_filters, fy):
    """Merge TL rows from multiple type_filters."""
    all_rows = [get_team_leader_rows(cursor, office_id, tf, fy) for tf in type_filters]
    return _merge_sub_rows(all_rows, 'officer_id')


def get_combined_officer_rows(cursor, tl_id, type_filters, fy, include_dev=False):
    """Merge officer rows from multiple type_filters."""
    all_rows = [get_officer_rows(cursor, tl_id, tf, fy) for tf in type_filters]
    if include_dev:
        all_rows.append(get_development_officer_rows(cursor, tl_id, fy))
    merged = _merge_sub_rows(all_rows, 'officer_id')
    # Fix annual_target: _merge_sub_rows sums it across tabs, but it should be per-officer
    # Look up actual annual_target for each officer
    for row in merged:
        oid = row.get('officer_id')
        if oid:
            try:
                cursor.execute(f"SELECT COALESCE(annual_target, 60.0) as at FROM officers WHERE officer_id = {PH}", [oid])
                r = cursor.fetchone()
                if r:
                    row['annual_target'] = r['at']
            except Exception:
                pass
    return merged


def get_scoped_summary(cursor, sub_view, sub_id, active_tab, fy, user):
    """Compute 10 summary cards narrowed to a sub_id scope.
    Re-uses get_tab_summary() logic but with a narrowed WHERE clause."""
    if sub_view == 'team_leaders':
        where = f"WHERE a.office_id = {PH}"
        params = [sub_id]
        view_type = 'office'
    elif sub_view == 'officers':
        where = f"WHERE a.team_leader_officer_id = {PH}"
        params = [sub_id]
        view_type = 'team_leader'
    elif sub_view == 'items' and sub_id:
        where = "INDIVIDUAL"
        params = [sub_id]
        view_type = 'individual'
        scoped_user = dict(user)
        scoped_user['officer_id'] = sub_id
        return get_tab_summary(cursor, active_tab, where, params, view_type, scoped_user, fy)
    else:
        return None

    return get_tab_summary(cursor, active_tab, where, params, view_type, user, fy)


def build_breadcrumbs(cursor, sub_view, sub_id, active_tab, fy, active_role, scope_value):
    """Build breadcrumb trail for hierarchical navigation."""
    base_url = f"/dashboard?active_tab={active_tab}&fy={fy}"
    crumbs = []

    if active_role in ('DG', 'DDG-I', 'DDG-II', 'ADMIN'):
        crumbs.append({'label': 'All Offices', 'url': base_url})

        if sub_view in ('team_leaders', 'officers', 'items') and sub_id:
            if sub_view == 'team_leaders':
                # sub_id is office_id - look up name
                cursor.execute(f"SELECT office_name FROM offices WHERE office_id = {PH}", (sub_id,))
                row = cursor.fetchone()
                label = row['office_name'] if row else sub_id
                crumbs.append({'label': label, 'url': f"{base_url}&sub_view=team_leaders&sub_id={sub_id}"})

            elif sub_view == 'officers':
                # sub_id is TL officer_id - need to find their office first
                cursor.execute(f"SELECT name, office_id FROM officers WHERE officer_id = {PH}", (sub_id,))
                row = cursor.fetchone()
                if row:
                    tl_name = row['name']
                    tl_office = row['office_id']
                    # Add office crumb
                    cursor.execute(f"SELECT office_name FROM offices WHERE office_id = {PH}", (tl_office,))
                    orow = cursor.fetchone()
                    office_label = orow['office_name'] if orow else tl_office
                    crumbs.append({'label': office_label, 'url': f"{base_url}&sub_view=team_leaders&sub_id={tl_office}"})
                    crumbs.append({'label': f"TL: {tl_name}", 'url': f"{base_url}&sub_view=officers&sub_id={sub_id}"})

            elif sub_view == 'items':
                # sub_id is officer_id
                cursor.execute(f"SELECT name, office_id FROM officers WHERE officer_id = {PH}", (sub_id,))
                row = cursor.fetchone()
                if row:
                    off_name = row['name']
                    off_office = row['office_id']
                    cursor.execute(f"SELECT office_name FROM offices WHERE office_id = {PH}", (off_office,))
                    orow = cursor.fetchone()
                    office_label = orow['office_name'] if orow else off_office
                    crumbs.append({'label': office_label, 'url': f"{base_url}&sub_view=team_leaders&sub_id={off_office}"})
                    # We don't know which TL the officer belongs to without more context,
                    # so skip TL crumb for now
                    crumbs.append({'label': off_name, 'url': f"{base_url}&sub_view=items&sub_id={sub_id}"})

    elif active_role in ('GROUP_HEAD', 'RD_HEAD'):
        label = f"{'Group' if active_role == 'GROUP_HEAD' else 'Office'}: {scope_value}"
        crumbs.append({'label': label, 'url': base_url})

        if sub_view == 'officers' and sub_id:
            cursor.execute(f"SELECT name FROM officers WHERE officer_id = {PH}", (sub_id,))
            row = cursor.fetchone()
            tl_name = row['name'] if row else sub_id
            crumbs.append({'label': f"TL: {tl_name}", 'url': f"{base_url}&sub_view=officers&sub_id={sub_id}"})

        elif sub_view == 'items' and sub_id:
            cursor.execute(f"SELECT name FROM officers WHERE officer_id = {PH}", (sub_id,))
            row = cursor.fetchone()
            crumbs.append({'label': row['name'] if row else sub_id, 'url': f"{base_url}&sub_view=items&sub_id={sub_id}"})

    elif active_role == 'TEAM_LEADER':
        crumbs.append({'label': 'My Team', 'url': base_url})
        if sub_view == 'items' and sub_id:
            cursor.execute(f"SELECT name FROM officers WHERE officer_id = {PH}", (sub_id,))
            row = cursor.fetchone()
            crumbs.append({'label': row['name'] if row else sub_id, 'url': f"{base_url}&sub_view=items&sub_id={sub_id}"})

    return crumbs


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    active_tab: Optional[str] = Query("assignments"),
    fy: Optional[str] = Query(None),
    sub_view: Optional[str] = Query(None),
    sub_id: Optional[str] = Query(None),
    filter_office: Optional[str] = Query(None),
    filter_status: Optional[str] = Query(None),
    show_all: bool = Query(False)
):
    """Display the main dashboard with role-based views, 3 tabs, and hierarchical sub-views."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if active_tab not in ('assignments', 'training', 'total_real_revenue', 'development', 'total_revenue'):
        active_tab = 'assignments'

    current_fy = fy or get_current_fy()
    fy_progress = calculate_fy_progress()
    active_role, scope_type, scope_value = get_active_role_info(user)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get role-based filter
        role_offices = []
        role_groups = []
        if active_role in ('DDG-I', 'DDG-II'):
            role_offices = get_offices_for_ddg(cursor, active_role)
            role_groups = get_groups_for_ddg(cursor, active_role)

        role_where, role_params, view_title, view_type = build_role_filter(
            active_role, scope_value, user, role_offices, role_groups
        )

        # Back-compat: filter_office → sub_view=team_leaders&sub_id=filter_office
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

        # Validate sub_view
        if sub_view not in ('entities', 'team_leaders', 'officers', 'items'):
            sub_view = 'items'

        # Tab counts (always at full role scope)
        tab_counts = get_tab_counts(cursor, role_where, role_params, view_type, user)

        # Summary cards: scoped if sub_id is set, else full role scope
        if sub_id and sub_view != 'entities' and active_tab != 'development':
            tab_summary = get_scoped_summary(cursor, sub_view, sub_id, active_tab, current_fy, user)
            if not tab_summary:
                tab_summary = get_tab_summary(cursor, active_tab, role_where, role_params, view_type, user, current_fy)
        else:
            tab_summary = get_tab_summary(cursor, active_tab, role_where, role_params, view_type, user, current_fy)

        # Sub-view content
        sub_rows = []
        items = []

        # Determine which type_filters to use for sub-view aggregation
        if active_tab == 'assignments':
            type_filters = ['ASSIGNMENT']
        elif active_tab == 'training':
            type_filters = ['TRAINING']
        elif active_tab == 'total_real_revenue':
            type_filters = ['ASSIGNMENT', 'TRAINING']
        elif active_tab == 'total_revenue':
            type_filters = ['ASSIGNMENT', 'TRAINING']  # dev handled separately
        else:
            type_filters = []

        is_combined_tab = active_tab in ('total_real_revenue', 'total_revenue')

        if sub_view == 'items' or (active_tab == 'development' and sub_view not in ('entities', 'team_leaders', 'officers')):
            # Show item list for items sub_view, or development tab at default level
            # For combined tabs at items level, show assignments tab items
            item_tab = 'assignments' if is_combined_tab else active_tab
            items = get_tab_items(cursor, item_tab, role_where, role_params, view_type, user,
                                  sub_id if sub_view == 'items' else filter_office, filter_status)
            # For items sub_view with sub_id, filter to that officer's items
            if sub_view == 'items' and sub_id and item_tab != 'development':
                items = get_tab_items(cursor, item_tab, "INDIVIDUAL", [sub_id], 'individual',
                                      {'officer_id': sub_id}, None, filter_status)

        elif sub_view == 'entities':
            all_ids = role_offices + role_groups
            if active_role in ('DG', 'ADMIN'):
                cursor.execute("SELECT office_id FROM offices ORDER BY office_id")
                all_ids = [row['office_id'] for row in cursor.fetchall()]
            if is_combined_tab:
                sub_rows = get_combined_entity_rows(cursor, all_ids, type_filters, current_fy)
            else:
                sub_rows = get_entity_rows(cursor, all_ids, type_filters[0], current_fy)

        elif sub_view == 'team_leaders':
            office_id = sub_id or scope_value
            if office_id:
                if is_combined_tab:
                    sub_rows = get_combined_tl_rows(cursor, office_id, type_filters, current_fy)
                else:
                    sub_rows = get_team_leader_rows(cursor, office_id, type_filters[0], current_fy)

        elif sub_view == 'officers':
            tl_id = sub_id if sub_id else (user['officer_id'] if active_role == 'TEAM_LEADER' else None)
            if tl_id:
                if active_tab == 'development':
                    sub_rows = get_development_officer_rows(cursor, tl_id, current_fy)
                elif active_tab == 'total_revenue':
                    sub_rows = get_combined_officer_rows(cursor, tl_id, type_filters, current_fy, include_dev=True)
                elif is_combined_tab:
                    sub_rows = get_combined_officer_rows(cursor, tl_id, type_filters, current_fy)
                else:
                    sub_rows = get_officer_rows(cursor, tl_id, type_filters[0], current_fy)

        # Breadcrumbs
        breadcrumbs = build_breadcrumbs(cursor, sub_view, sub_id, active_tab, current_fy, active_role, scope_value)

        # Available FYs
        financial_years = get_available_fys(cursor)

        # Statuses for filter
        cursor.execute("SELECT DISTINCT status FROM assignments WHERE status IS NOT NULL ORDER BY status")
        statuses = [row['status'] for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "view": view_type,
            "view_title": view_title,
            "active_role": active_role,
            "scope_value": scope_value,
            "active_tab": active_tab,
            "current_fy": current_fy,
            "financial_years": financial_years,
            "tab_counts": tab_counts,
            "tab_summary": tab_summary,
            "items": items,
            "sub_view": sub_view,
            "sub_id": sub_id,
            "sub_rows": sub_rows,
            "breadcrumbs": breadcrumbs,
            "statuses": statuses,
            "filter_status": filter_status,
            "show_all": show_all,
            "fy_progress": fy_progress,
            "role_offices": role_offices,
            "role_groups": role_groups,
        }
    )


@router.get("/api/monthly-breakdown", response_class=JSONResponse)
async def monthly_breakdown(
    request: Request,
    tab: str = Query("assignments"),
    metric: str = Query("billing"),
    fy: Optional[str] = Query(None),
    view: str = Query("monthly"),
    sub_view: Optional[str] = Query(None),
    sub_id: Optional[str] = Query(None)
):
    """Return breakdown data for a metric as JSON.

    view: 'monthly' (12 months Apr-Mar), 'quarterly' (Q1-Q4), 'till_date' (single cumulative)
    sub_view/sub_id: Optional scoping for hierarchical drill-down.
    """
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    current_fy = fy or get_current_fy()
    fy_start, fy_end = get_fy_date_range(current_fy)
    active_role, scope_type, scope_value = get_active_role_info(user)

    with get_db() as conn:
        cursor = conn.cursor()

        role_offices = []
        role_groups = []
        if active_role in ('DDG-I', 'DDG-II'):
            role_offices = get_offices_for_ddg(cursor, active_role)
            role_groups = get_groups_for_ddg(cursor, active_role)

        role_where, role_params, _, view_type = build_role_filter(
            active_role, scope_value, user, role_offices, role_groups
        )

        # Narrow scope for hierarchical sub-views
        if sub_id and sub_view:
            if sub_view == 'team_leaders':
                # sub_id is office_id
                role_where = f"WHERE a.office_id = {PH}"
                role_params = [sub_id]
                view_type = 'office'
            elif sub_view == 'officers':
                # sub_id is TL officer_id
                role_where = f"WHERE a.team_leader_officer_id = {PH}"
                role_params = [sub_id]
                view_type = 'team_leader'
            elif sub_view == 'items':
                # sub_id is officer_id
                role_where = "INDIVIDUAL"
                role_params = [sub_id]
                view_type = 'individual'

        # Determine type_filters for combined tabs
        if tab == 'total_real_revenue':
            type_filter_list = ['ASSIGNMENT', 'TRAINING']
        elif tab == 'total_revenue':
            type_filter_list = ['ASSIGNMENT', 'TRAINING']
        elif tab == 'assignments':
            type_filter_list = ['ASSIGNMENT']
        elif tab == 'training':
            type_filter_list = ['TRAINING']
        else:
            type_filter_list = []

        month_labels = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar']
        month_nums = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
        monthly = [0] * 12

        if tab == 'development' or not type_filter_list:
            return JSONResponse({"labels": month_labels, "data": monthly, "metric": metric})

        def _build_role_join(view_type, user, role_params, tf):
            """Return (extra_join, where_clause, params) based on view_type."""
            if view_type == 'individual':
                return (
                    "JOIN revenue_shares rs ON a.id = rs.assignment_id",
                    f"WHERE rs.officer_id = {PH} AND a.type = {PH}",
                    [user['officer_id'], tf]
                )
            else:
                return (
                    "",
                    f"{role_where} AND a.type = {PH}",
                    list(role_params) + [tf]
                )

        # Helper: fetch monthly amounts from a query and accumulate into monthly[]
        def _accumulate_monthly(cursor_result):
            for row in cursor_result:
                m = int(row['m'])
                if m in month_nums:
                    idx = month_nums.index(m)
                    monthly[idx] += round(row['amt'] or 0, 2)

        # For computed metrics that combine two sub-metrics
        payments_monthly = [0] * 12
        expenses_monthly = [0] * 12
        completed_monthly = [0] * 12
        need_payments = metric in ('payments', 'net_value', 'surplus_deficit')
        need_expenses = metric in ('expenses', 'net_value', 'surplus_deficit')
        need_completed = metric in ('completed', 'net_value')

        # Loop over type_filters (for combined tabs, sums both ASSIGNMENT + TRAINING)
        for type_filter in type_filter_list:
            extra_join, where_clause, base_params = _build_role_join(view_type, user, role_params, type_filter)
            is_training = (type_filter == 'TRAINING')

            if metric == 'active_count':
                # Count active items by start_date month
                if USE_POSTGRES:
                    month_expr = "EXTRACT(MONTH FROM a.start_date)::integer"
                else:
                    month_expr = "CAST(strftime('%m', a.start_date) AS INTEGER)"

                cursor.execute(f"""
                    SELECT {month_expr} as m, COUNT(*) as amt
                    FROM assignments a
                    {extra_join}
                    {where_clause}
                    AND a.status IN ('In Progress', 'Not Started', 'Ongoing')
                    AND a.start_date >= {PH} AND a.start_date <= {PH}
                    GROUP BY {month_expr}
                """, base_params + [fy_start, fy_end])
                _accumulate_monthly(cursor.fetchall())

            elif metric == 'targeted':
                # Targeted value by assignment start_date month
                if USE_POSTGRES:
                    month_expr = "EXTRACT(MONTH FROM a.start_date)::integer"
                else:
                    month_expr = "CAST(strftime('%m', a.start_date) AS INTEGER)"

                if is_training:
                    cursor.execute(f"""
                        SELECT {month_expr} as m,
                               COALESCE(SUM(a.target_participants * a.fee_per_participant), 0) as amt
                        FROM assignments a
                        {extra_join}
                        {where_clause}
                        AND a.start_date >= {PH} AND a.start_date <= {PH}
                        GROUP BY {month_expr}
                    """, base_params + [fy_start, fy_end])
                else:
                    cursor.execute(f"""
                        SELECT {month_expr} as m,
                               COALESCE(SUM(a.gross_value), 0) as amt
                        FROM assignments a
                        {extra_join}
                        {where_clause}
                        AND a.start_date >= {PH} AND a.start_date <= {PH}
                        GROUP BY {month_expr}
                    """, base_params + [fy_start, fy_end])
                _accumulate_monthly(cursor.fetchall())

            elif metric == 'tentative':
                # Tentative value by milestone tentative_date month
                if is_training:
                    if USE_POSTGRES:
                        month_expr = "EXTRACT(MONTH FROM a.start_date)::integer"
                    else:
                        month_expr = "CAST(strftime('%m', a.start_date) AS INTEGER)"
                    cursor.execute(f"""
                        SELECT {month_expr} as m,
                               COALESCE(SUM(a.tentative_participants * a.fee_per_participant), 0) as amt
                        FROM assignments a
                        {extra_join}
                        {where_clause}
                        AND a.start_date >= {PH} AND a.start_date <= {PH}
                        GROUP BY {month_expr}
                    """, base_params + [fy_start, fy_end])
                else:
                    if USE_POSTGRES:
                        month_expr = "EXTRACT(MONTH FROM m.tentative_date)::integer"
                    else:
                        month_expr = "CAST(strftime('%m', m.tentative_date) AS INTEGER)"
                    cursor.execute(f"""
                        SELECT {month_expr} as m,
                               COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0), 0) as amt
                        FROM milestones m
                        JOIN assignments a ON m.assignment_id = a.id
                        {extra_join}
                        {where_clause}
                        AND m.tentative_date >= {PH} AND m.tentative_date <= {PH}
                        GROUP BY {month_expr}
                    """, base_params + [fy_start, fy_end])
                _accumulate_monthly(cursor.fetchall())

            elif metric == 'completed' or need_completed:
                # Completed value by milestone completion (target_date for completed milestones)
                if USE_POSTGRES:
                    month_expr_m = "EXTRACT(MONTH FROM m.target_date)::integer"
                else:
                    month_expr_m = "CAST(strftime('%m', m.target_date) AS INTEGER)"

                if is_training:
                    # For training, use actual_participants * fee by start_date
                    if USE_POSTGRES:
                        month_expr_a = "EXTRACT(MONTH FROM a.start_date)::integer"
                    else:
                        month_expr_a = "CAST(strftime('%m', a.start_date) AS INTEGER)"
                    cursor.execute(f"""
                        SELECT {month_expr_a} as m,
                               COALESCE(SUM(a.actual_participants * a.fee_per_participant), 0) as amt
                        FROM assignments a
                        {extra_join}
                        {where_clause}
                        AND a.status = 'Completed'
                        AND a.start_date >= {PH} AND a.start_date <= {PH}
                        GROUP BY {month_expr_a}
                    """, base_params + [fy_start, fy_end])
                else:
                    cursor.execute(f"""
                        SELECT {month_expr_m} as m,
                               COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0), 0) as amt
                        FROM milestones m
                        JOIN assignments a ON m.assignment_id = a.id
                        {extra_join}
                        {where_clause}
                        AND m.status = 'Completed'
                        AND m.target_date >= {PH} AND m.target_date <= {PH}
                        GROUP BY {month_expr_m}
                    """, base_params + [fy_start, fy_end])

                for row in cursor.fetchall():
                    m_val = int(row['m'])
                    if m_val in month_nums:
                        idx = month_nums.index(m_val)
                        val = round(row['amt'] or 0, 2)
                        completed_monthly[idx] += val
                        if metric == 'completed':
                            monthly[idx] += val

            if metric in ('billing', 'to_be_billed'):
                if USE_POSTGRES:
                    month_expr = "EXTRACT(MONTH FROM ir.requested_at)::integer"
                else:
                    month_expr = "CAST(strftime('%m', ir.requested_at) AS INTEGER)"

                if metric == 'billing':
                    cursor.execute(f"""
                        SELECT {month_expr} as m, COALESCE(SUM(ir.invoice_amount), 0) as amt
                        FROM invoice_requests ir
                        JOIN assignments a ON ir.assignment_id = a.id
                        {extra_join}
                        {where_clause}
                        AND ir.fy_period = {PH}
                        GROUP BY {month_expr}
                    """, base_params + [current_fy])
                else:
                    if USE_POSTGRES:
                        month_expr_m = "EXTRACT(MONTH FROM m.target_date)::integer"
                    else:
                        month_expr_m = "CAST(strftime('%m', m.target_date) AS INTEGER)"

                    cursor.execute(f"""
                        SELECT {month_expr_m} as m, COALESCE(SUM(a.gross_value * m.revenue_percent / 100.0), 0) as amt
                        FROM milestones m
                        JOIN assignments a ON m.assignment_id = a.id
                        {extra_join}
                        {where_clause}
                        AND m.target_date >= {PH} AND m.target_date <= {PH}
                        AND m.invoice_raised = 0
                        GROUP BY {month_expr_m}
                    """, base_params + [fy_start, fy_end])

                _accumulate_monthly(cursor.fetchall())

            # Payments: fetch for 'payments' metric or when needed by net_value/surplus_deficit
            if metric == 'payments' or need_payments:
                if USE_POSTGRES:
                    month_expr = "EXTRACT(MONTH FROM pr.receipt_date)::integer"
                else:
                    month_expr = "CAST(strftime('%m', pr.receipt_date) AS INTEGER)"

                cursor.execute(f"""
                    SELECT {month_expr} as m, COALESCE(SUM(pr.amount_received), 0) as amt
                    FROM payment_receipts pr
                    JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
                    JOIN assignments a ON ir.assignment_id = a.id
                    {extra_join}
                    {where_clause} AND pr.fy_period = {PH}
                    GROUP BY {month_expr}
                """, base_params + [current_fy])

                for row in cursor.fetchall():
                    m_val = int(row['m'])
                    if m_val in month_nums:
                        idx = month_nums.index(m_val)
                        val = round(row['amt'] or 0, 2)
                        payments_monthly[idx] += val
                        if metric == 'payments':
                            monthly[idx] += val

            # Expenses: fetch for 'expenses' metric or when needed by net_value/surplus_deficit
            if metric == 'expenses' or need_expenses:
                if USE_POSTGRES:
                    month_expr = "EXTRACT(MONTH FROM ee.entry_date)::integer"
                else:
                    month_expr = "CAST(strftime('%m', ee.entry_date) AS INTEGER)"

                try:
                    cursor.execute(f"""
                        SELECT {month_expr} as m, COALESCE(SUM(ee.amount), 0) as amt
                        FROM expenditure_entries ee
                        JOIN assignments a ON ee.assignment_id = a.id
                        {extra_join}
                        {where_clause} AND ee.fy_period = {PH}
                        GROUP BY {month_expr}
                    """, base_params + [current_fy])

                    for row in cursor.fetchall():
                        m_val = int(row['m'])
                        if m_val in month_nums:
                            idx = month_nums.index(m_val)
                            val = round(row['amt'] or 0, 2)
                            expenses_monthly[idx] += val
                            if metric == 'expenses':
                                monthly[idx] += val
                except Exception:
                    pass

        # Compute derived metrics
        if metric == 'net_value':
            monthly = [round(completed_monthly[i] - expenses_monthly[i], 2) for i in range(12)]
        elif metric == 'surplus_deficit':
            monthly = [round(payments_monthly[i] - expenses_monthly[i], 2) for i in range(12)]

    # Convert to requested view
    if view == 'quarterly':
        # Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar
        quarterly = [
            round(sum(monthly[0:3]), 2),
            round(sum(monthly[3:6]), 2),
            round(sum(monthly[6:9]), 2),
            round(sum(monthly[9:12]), 2),
        ]
        return JSONResponse({
            "labels": ["Q1 (Apr-Jun)", "Q2 (Jul-Sep)", "Q3 (Oct-Dec)", "Q4 (Jan-Mar)"],
            "data": quarterly,
            "metric": metric,
            "fy": current_fy
        })
    elif view == 'till_date':
        total = round(sum(monthly), 2)
        return JSONResponse({
            "labels": [f"FY {current_fy} Total"],
            "data": [total],
            "metric": metric,
            "fy": current_fy
        })
    else:
        return JSONResponse({
            "labels": month_labels,
            "data": monthly,
            "metric": metric,
            "fy": current_fy
        })


@router.get("/summary", response_class=HTMLResponse)
async def dashboard_summary(request: Request):
    """Display summary statistics for the dashboard."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT
                COUNT(*) as total_assignments,
                SUM(CASE WHEN type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as total_projects,
                SUM(CASE WHEN type = 'TRAINING' THEN 1 ELSE 0 END) as total_trainings,
                SUM(COALESCE(total_revenue, 0)) as total_revenue,
                SUM(COALESCE(amount_received, 0)) as total_received
            FROM assignments
            WHERE office_id = {PH}
        """, (user['office_id'],))
        summary = dict(cursor.fetchone())

        cursor.execute(f"""
            SELECT SUM(share_amount) as my_total_share
            FROM revenue_shares
            WHERE officer_id = {PH}
        """, (user['officer_id'],))
        row = cursor.fetchone()
        summary['my_total_share'] = row['my_total_share'] or 0

    return templates.TemplateResponse(
        "dashboard_summary.html",
        {
            "request": request,
            "user": user,
            "summary": summary
        }
    )
