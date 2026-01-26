"""
Dashboard routes: assignment list and main dashboard.
Supports three views: Individual, Office, and NPC (organization-wide).
"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db
from app.dependencies import get_current_user
from app.templates_config import templates

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


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    view: Optional[str] = Query("individual"),  # individual, office, npc
    filter_office: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None),
    filter_status: Optional[str] = Query(None),
    show_all: bool = Query(False)
):
    """Display the main dashboard with three view modes: Individual, Office, NPC."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()

        # Check if user has admin/head role for NPC view access
        cursor.execute("""
            SELECT role_type FROM officer_roles
            WHERE officer_id = ? AND role_type IN ('ADMIN', 'DG', 'DDG', 'HEAD')
        """, (user['officer_id'],))
        user_roles = [row['role_type'] for row in cursor.fetchall()]
        can_view_npc = len(user_roles) > 0 or user.get('admin_role_id') in ['ADMIN', 'DG', 'DDG']

        # Determine actual view based on permissions
        if view == 'npc' and not can_view_npc:
            view = 'office'

        # Build query based on view
        if view == 'individual':
            # Show only assignments where user has revenue share
            query = """
                SELECT DISTINCT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled,
                    rs.share_percent, rs.share_amount
                FROM assignments a
                JOIN revenue_shares rs ON a.id = rs.assignment_id
                WHERE rs.officer_id = ?
            """
            params = [user['officer_id']]
        elif view == 'office':
            # Show all assignments in user's office
            query = """
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE a.office_id = ?
            """
            params = [user['office_id']]
        else:  # npc view
            # Show all assignments across organization
            query = """
                SELECT
                    a.id, a.assignment_no, a.type, a.title, a.client, a.office_id,
                    a.status, a.gross_value, a.invoice_amount, a.amount_received,
                    a.total_revenue, a.details_filled,
                    (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
                FROM assignments a
                WHERE 1=1
            """
            params = []

        # Apply additional filters
        if filter_office and view == 'npc':
            query += " AND a.office_id = ?"
            params.append(filter_office)

        if filter_type:
            query += " AND a.type = ?"
            params.append(filter_type)

        if filter_status:
            query += " AND a.status = ?"
            params.append(filter_status)

        query += " ORDER BY a.assignment_no DESC LIMIT 50"

        cursor.execute(query, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get summary stats based on view
        if view == 'individual':
            # Individual stats: officer's own performance
            cursor.execute("""
                SELECT
                    COUNT(DISTINCT rs.assignment_id) as assignment_count,
                    COALESCE(SUM(rs.share_amount), 0) as total_share,
                    o.annual_target
                FROM revenue_shares rs
                JOIN officers o ON rs.officer_id = o.officer_id
                WHERE rs.officer_id = ?
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
            cursor.execute("""
                SELECT COALESCE(SUM(notional_value), 0) as notional
                FROM non_revenue_suggestions
                WHERE officer_id = ? AND status = 'COMPLETED'
            """, (user['officer_id'],))
            notional_row = cursor.fetchone()
            summary['notional_revenue'] = notional_row['notional'] if notional_row else 0
            summary['total_contribution'] = summary['total_share'] + summary['notional_revenue']

        elif view == 'office':
            # Office stats
            cursor.execute("""
                SELECT
                    COUNT(*) as assignment_count,
                    COALESCE(SUM(total_revenue), 0) as total_revenue,
                    o.annual_revenue_target as target,
                    o.officer_count
                FROM assignments a
                JOIN offices o ON a.office_id = o.office_id
                WHERE a.office_id = ?
                GROUP BY o.annual_revenue_target, o.officer_count
            """, (user['office_id'],))
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
            cursor.execute("""
                SELECT COALESCE(SUM(notional_value), 0) as notional
                FROM non_revenue_suggestions
                WHERE office_id = ? AND status = 'COMPLETED'
            """, (user['office_id'],))
            notional_row = cursor.fetchone()
            summary['notional_revenue'] = notional_row['notional'] if notional_row else 0
            summary['total_contribution'] = summary['total_revenue'] + summary['notional_revenue']

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

        # Get offices for filter dropdown (only for NPC view)
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

        # Get unique statuses for filter
        cursor.execute("SELECT DISTINCT status FROM assignments WHERE status IS NOT NULL ORDER BY status")
        statuses = [row['status'] for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "view": view,
            "can_view_npc": can_view_npc,
            "assignments": assignments,
            "summary": summary,
            "offices": offices,
            "statuses": statuses,
            "filter_office": filter_office,
            "filter_type": filter_type,
            "filter_status": filter_status,
            "show_all": show_all,
            "fy_progress": fy_progress
        }
    )


@router.get("/summary", response_class=HTMLResponse)
async def dashboard_summary(request: Request):
    """Display summary statistics for the dashboard."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get summary stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_assignments,
                SUM(CASE WHEN type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as total_projects,
                SUM(CASE WHEN type = 'TRAINING' THEN 1 ELSE 0 END) as total_trainings,
                SUM(COALESCE(total_revenue, 0)) as total_revenue,
                SUM(COALESCE(amount_received, 0)) as total_received
            FROM assignments
            WHERE office_id = ?
        """, (user['office_id'],))
        summary = dict(cursor.fetchone())

        # Get officer's personal share
        cursor.execute("""
            SELECT SUM(share_amount) as my_total_share
            FROM revenue_shares
            WHERE officer_id = ?
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
