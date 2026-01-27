"""
Dashboard routes: assignment list and main dashboard.
Role-based views: DG, DDG, Group Head, RD Head, Team Leader, Individual.
"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user
from app.templates_config import templates
from app.roles import get_user_roles

router = APIRouter()


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
    ph = '%s' if USE_POSTGRES else '?'
    cursor.execute(f"""
        SELECT entity_value FROM reporting_hierarchy
        WHERE entity_type = 'OFFICE' AND reports_to_role = {ph}
    """, (ddg_role,))
    return [row['entity_value'] for row in cursor.fetchall()]


def get_groups_for_ddg(cursor, ddg_role: str):
    """Get list of groups that report to a DDG role."""
    ph = '%s' if USE_POSTGRES else '?'
    cursor.execute(f"""
        SELECT entity_value FROM reporting_hierarchy
        WHERE entity_type = 'GROUP' AND reports_to_role = {ph}
    """, (ddg_role,))
    return [row['entity_value'] for row in cursor.fetchall()]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    filter_office: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None),
    filter_status: Optional[str] = Query(None),
    show_all: bool = Query(False)
):
    """Display the main dashboard with role-based views."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    # Get user's active role and its scope
    active_role, scope_type, scope_value = get_active_role_info(user)

    with get_db() as conn:
        cursor = conn.cursor()

        # Initialize variables
        view_title = "My Dashboard"
        view_type = "individual"
        role_offices = []
        role_groups = []

        # Build query based on active role
        if active_role == 'DG':
            # DG sees all organization data
            view_title = "Director General View"
            view_type = "npc"
            query = """
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled, a.team_leader_officer_id,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE 1=1
            """
            params = []

        elif active_role in ('DDG-I', 'DDG-II'):
            # DDG sees offices and groups reporting to them
            # Both regional offices (CHN, HYD) and group offices (HRM, IE) use office_id
            view_title = f"{active_role} View"
            view_type = "ddg"

            role_offices = get_offices_for_ddg(cursor, active_role)
            role_groups = get_groups_for_ddg(cursor, active_role)

            # Combine offices and groups - both are matched against office_id
            all_office_ids = role_offices + role_groups

            if all_office_ids:
                ph = '%s' if USE_POSTGRES else '?'
                placeholders = ','.join([ph for _ in all_office_ids])

                query = f"""
                    SELECT
                        a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                        a.status, a.gross_value, a.invoice_amount, a.amount_received,
                        a.total_revenue, a.details_filled, a.team_leader_officer_id, a.domain,
                        (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                    FROM assignments a
                    WHERE a.office_id IN ({placeholders})
                """
                params = all_office_ids
            else:
                query = """
                    SELECT
                        a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                        a.status, a.gross_value, a.invoice_amount, a.amount_received,
                        a.total_revenue, a.details_filled, a.team_leader_officer_id,
                        (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                    FROM assignments a
                    WHERE 1=0
                """
                params = []

        elif active_role == 'GROUP_HEAD' and scope_value:
            # Group Head sees assignments in their group office (e.g., office_id = 'HRM', 'IE', 'Finance')
            view_title = f"Group Head ({scope_value}) View"
            view_type = "group"
            ph = '%s' if USE_POSTGRES else '?'
            query = f"""
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled, a.team_leader_officer_id, a.domain,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE a.office_id = {ph}
            """
            params = [scope_value]

        elif active_role == 'RD_HEAD' and scope_value:
            # RD Head sees assignments in their office
            view_title = f"RD Head ({scope_value}) View"
            view_type = "office"
            ph = '%s' if USE_POSTGRES else '?'
            query = f"""
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled, a.team_leader_officer_id,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE a.office_id = {ph}
            """
            params = [scope_value]

        elif active_role == 'TEAM_LEADER':
            # Team Leader sees assignments where they are TL
            view_title = "Team Leader View"
            view_type = "team_leader"
            ph = '%s' if USE_POSTGRES else '?'
            query = f"""
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled, a.team_leader_officer_id,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE a.team_leader_officer_id = {ph}
            """
            params = [user['officer_id']]

        elif active_role == 'ADMIN':
            # Admin sees everything
            view_title = "Administrator View"
            view_type = "npc"
            query = """
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled, a.team_leader_officer_id,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE 1=1
            """
            params = []

        else:
            # OFFICER (Individual) - shows assignments where user has revenue share
            view_title = "My Dashboard"
            view_type = "individual"
            ph = '%s' if USE_POSTGRES else '?'
            query = f"""
                SELECT DISTINCT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled,
                    rs.share_percent, rs.share_amount
                FROM assignments a
                JOIN revenue_shares rs ON a.id = rs.assignment_id
                WHERE rs.officer_id = {ph}
            """
            params = [user['officer_id']]

        # Apply additional filters
        ph = '%s' if USE_POSTGRES else '?'
        if filter_office and view_type in ('npc', 'ddg'):
            query += f" AND a.office_id = {ph}"
            params.append(filter_office)

        if filter_type:
            query += f" AND a.type = {ph}"
            params.append(filter_type)

        if filter_status:
            query += f" AND a.status = {ph}"
            params.append(filter_status)

        query += " ORDER BY a.assignment_no DESC LIMIT 100"

        cursor.execute(query, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get summary stats based on view type
        summary = get_summary_stats(cursor, user, view_type, active_role, scope_value,
                                    role_offices, role_groups, fy_progress)

        # Get offices for filter dropdown
        if view_type in ('npc', 'ddg'):
            if role_offices:
                ph = '%s' if USE_POSTGRES else '?'
                cursor.execute(f"""
                    SELECT office_id, office_name FROM offices
                    WHERE office_id IN ({','.join([ph for _ in role_offices])})
                    ORDER BY office_id
                """, role_offices)
            else:
                cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
            offices = [dict(row) for row in cursor.fetchall()]
        else:
            offices = []

        # Get unique statuses for filter
        cursor.execute("SELECT DISTINCT status FROM assignments WHERE status IS NOT NULL ORDER BY status")
        statuses = [row['status'] for row in cursor.fetchall()]

        # Check if user can view NPC (for showing tabs)
        can_view_npc = active_role in ('DG', 'DDG-I', 'DDG-II', 'ADMIN')

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "view": view_type,
            "view_title": view_title,
            "active_role": active_role,
            "scope_value": scope_value,
            "can_view_npc": can_view_npc,
            "assignments": assignments,
            "summary": summary,
            "offices": offices,
            "statuses": statuses,
            "filter_office": filter_office,
            "filter_type": filter_type,
            "filter_status": filter_status,
            "show_all": show_all,
            "fy_progress": fy_progress,
            "role_offices": role_offices,
            "role_groups": role_groups
        }
    )


def get_summary_stats(cursor, user, view_type, active_role, scope_value, role_offices, role_groups, fy_progress):
    """Get summary statistics based on view type."""
    summary = {}
    ph = '%s' if USE_POSTGRES else '?'

    if view_type == 'individual':
        # Individual stats: officer's own performance
        cursor.execute(f"""
            SELECT
                COUNT(DISTINCT rs.assignment_id) as assignment_count,
                COALESCE(SUM(rs.share_amount), 0) as total_share,
                o.annual_target
            FROM revenue_shares rs
            JOIN officers o ON rs.officer_id = o.officer_id
            WHERE rs.officer_id = {ph}
            GROUP BY o.annual_target
        """, (user['officer_id'],))
        row = cursor.fetchone()
        if row:
            summary = dict(row)
            target = summary.get('annual_target', 60) or 60
            summary['prorata_target'] = round(target * fy_progress, 2)
            summary['achievement_pct'] = round((summary['total_share'] / target * 100), 1) if target > 0 else 0
        else:
            summary = {'assignment_count': 0, 'total_share': 0, 'annual_target': 60,
                      'prorata_target': round(60 * fy_progress, 2), 'achievement_pct': 0}

        # Get notional revenue for individual
        cursor.execute(f"""
            SELECT COALESCE(SUM(notional_value), 0) as notional
            FROM non_revenue_suggestions
            WHERE officer_id = {ph} AND status = 'COMPLETED'
        """, (user['officer_id'],))
        notional_row = cursor.fetchone()
        summary['notional_revenue'] = notional_row['notional'] if notional_row else 0
        summary['total_contribution'] = summary['total_share'] + summary['notional_revenue']

    elif view_type == 'team_leader':
        # Team Leader stats
        cursor.execute(f"""
            SELECT
                COUNT(*) as assignment_count,
                COALESCE(SUM(total_revenue), 0) as total_revenue,
                COALESCE(SUM(gross_value), 0) as total_value
            FROM assignments
            WHERE team_leader_officer_id = {ph}
        """, (user['officer_id'],))
        row = cursor.fetchone()
        if row:
            summary = dict(row)
        else:
            summary = {'assignment_count': 0, 'total_revenue': 0, 'total_value': 0}
        summary['target'] = summary.get('total_value', 0)
        summary['prorata_target'] = round(summary['target'] * fy_progress, 2)
        summary['achievement_pct'] = round((summary['total_revenue'] / summary['target'] * 100), 1) if summary['target'] > 0 else 0
        summary['notional_revenue'] = 0
        summary['total_contribution'] = summary['total_revenue']

    elif view_type == 'office':
        # RD Head / Office stats
        office_id = scope_value or user['office_id']
        cursor.execute(f"""
            SELECT
                COUNT(*) as assignment_count,
                COALESCE(SUM(total_revenue), 0) as total_revenue,
                o.annual_revenue_target as target,
                o.officer_count
            FROM assignments a
            JOIN offices o ON a.office_id = o.office_id
            WHERE a.office_id = {ph}
            GROUP BY o.annual_revenue_target, o.officer_count
        """, (office_id,))
        row = cursor.fetchone()
        if row:
            summary = dict(row)
            target = summary.get('target', 0) or 0
            summary['prorata_target'] = round(target * fy_progress, 2)
            summary['achievement_pct'] = round((summary['total_revenue'] / target * 100), 1) if target > 0 else 0
        else:
            summary = {'assignment_count': 0, 'total_revenue': 0, 'target': 0,
                      'prorata_target': 0, 'achievement_pct': 0, 'officer_count': 0}

        # Get notional revenue for office
        cursor.execute(f"""
            SELECT COALESCE(SUM(notional_value), 0) as notional
            FROM non_revenue_suggestions
            WHERE office_id = {ph} AND status = 'COMPLETED'
        """, (office_id,))
        notional_row = cursor.fetchone()
        summary['notional_revenue'] = notional_row['notional'] if notional_row else 0
        summary['total_contribution'] = summary['total_revenue'] + summary['notional_revenue']

    elif view_type == 'group':
        # Group Head stats (by office_id, e.g., "HRM", "Finance", "IE" - group offices)
        cursor.execute(f"""
            SELECT
                COUNT(*) as assignment_count,
                COALESCE(SUM(total_revenue), 0) as total_revenue,
                COALESCE(SUM(gross_value), 0) as total_value
            FROM assignments
            WHERE office_id = {ph}
        """, (scope_value,))
        row = cursor.fetchone()
        if row:
            summary = dict(row)
        else:
            summary = {'assignment_count': 0, 'total_revenue': 0, 'total_value': 0}
        summary['target'] = summary.get('total_value', 0)
        summary['prorata_target'] = round(summary['target'] * fy_progress, 2)
        summary['achievement_pct'] = round((summary['total_revenue'] / summary['target'] * 100), 1) if summary['target'] > 0 else 0

        # Get officers count in this group office
        cursor.execute(f"""
            SELECT COUNT(DISTINCT rs.officer_id) as officer_count
            FROM revenue_shares rs
            JOIN assignments a ON rs.assignment_id = a.id
            WHERE a.office_id = {ph}
        """, (scope_value,))
        officer_row = cursor.fetchone()
        summary['officer_count'] = officer_row['officer_count'] if officer_row else 0
        summary['notional_revenue'] = 0
        summary['total_contribution'] = summary['total_revenue']

    elif view_type == 'ddg':
        # DDG view stats - aggregate of offices and groups reporting to DDG
        # Both offices and groups are matched against office_id (groups are stored as office_id too)
        all_office_ids = role_offices + role_groups

        if all_office_ids:
            placeholders = ','.join([ph for _ in all_office_ids])

            cursor.execute(f"""
                SELECT
                    COUNT(*) as assignment_count,
                    COALESCE(SUM(total_revenue), 0) as total_revenue,
                    COALESCE(SUM(gross_value), 0) as total_value
                FROM assignments
                WHERE office_id IN ({placeholders})
            """, all_office_ids)
            row = cursor.fetchone()
            if row:
                summary = dict(row)
            else:
                summary = {'assignment_count': 0, 'total_revenue': 0, 'total_value': 0}

            # Get target from offices (only actual offices, not groups)
            if role_offices:
                office_placeholders = ','.join([ph for _ in role_offices])
                cursor.execute(f"""
                    SELECT COALESCE(SUM(annual_revenue_target), 0) as target,
                           COUNT(*) as office_count,
                           COALESCE(SUM(officer_count), 0) as officer_count
                    FROM offices WHERE office_id IN ({office_placeholders})
                """, role_offices)
                target_row = cursor.fetchone()
                summary['target'] = target_row['target'] if target_row else 0
                summary['office_count'] = target_row['office_count'] if target_row else 0
                summary['officer_count'] = target_row['officer_count'] if target_row else 0
            else:
                summary['target'] = 0
                summary['office_count'] = 0
                summary['officer_count'] = 0

            # Add group count
            summary['group_count'] = len(role_groups)
        else:
            summary = {'assignment_count': 0, 'total_revenue': 0, 'total_value': 0,
                      'target': 0, 'office_count': 0, 'officer_count': 0, 'group_count': 0}

        summary['prorata_target'] = round(summary.get('target', 0) * fy_progress, 2)
        summary['achievement_pct'] = round((summary['total_revenue'] / summary['target'] * 100), 1) if summary.get('target', 0) > 0 else 0
        summary['notional_revenue'] = 0
        summary['total_contribution'] = summary['total_revenue']

    else:  # npc view
        # Organization-wide stats
        cursor.execute("""
            SELECT
                COUNT(*) as assignment_count,
                COALESCE(SUM(total_revenue), 0) as total_revenue,
                (SELECT COALESCE(SUM(annual_revenue_target), 0) FROM offices) as target,
                (SELECT COUNT(*) FROM officers WHERE is_active = 1) as officer_count,
                (SELECT COUNT(*) FROM offices) as office_count
            FROM assignments
        """)
        row = cursor.fetchone()
        summary = dict(row)
        target = summary.get('target', 0) or 0
        summary['prorata_target'] = round(target * fy_progress, 2)
        summary['achievement_pct'] = round((summary['total_revenue'] / target * 100), 1) if target > 0 else 0

        # Get notional revenue for NPC
        cursor.execute("""
            SELECT COALESCE(SUM(notional_value), 0) as notional
            FROM non_revenue_suggestions WHERE status = 'COMPLETED'
        """)
        notional_row = cursor.fetchone()
        summary['notional_revenue'] = notional_row['notional'] if notional_row else 0
        summary['total_contribution'] = summary['total_revenue'] + summary['notional_revenue']

    return summary


@router.get("/summary", response_class=HTMLResponse)
async def dashboard_summary(request: Request):
    """Display summary statistics for the dashboard."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        # Get summary stats
        cursor.execute(f"""
            SELECT
                COUNT(*) as total_assignments,
                SUM(CASE WHEN type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as total_projects,
                SUM(CASE WHEN type = 'TRAINING' THEN 1 ELSE 0 END) as total_trainings,
                SUM(COALESCE(total_revenue, 0)) as total_revenue,
                SUM(COALESCE(amount_received, 0)) as total_received
            FROM assignments
            WHERE office_id = {ph}
        """, (user['office_id'],))
        summary = dict(cursor.fetchone())

        # Get officer's personal share
        cursor.execute(f"""
            SELECT SUM(share_amount) as my_total_share
            FROM revenue_shares
            WHERE officer_id = {ph}
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
