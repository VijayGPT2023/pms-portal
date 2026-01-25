"""
Dashboard routes: assignment list and main dashboard.
"""
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    filter_office: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None),
    filter_status: Optional[str] = Query(None),
    show_all: bool = Query(False)
):
    """Display the main dashboard with assignment list."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Build query with filters
        query = """
            SELECT
                a.id,
                a.assignment_no,
                a.type,
                a.title,
                a.client,
                a.office_id,
                a.status,
                a.gross_value,
                a.invoice_amount,
                a.amount_received,
                a.total_revenue,
                a.details_filled,
                (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count
            FROM assignments a
            WHERE 1=1
        """
        params = []

        # Filter by officer's office unless show_all is True
        if not show_all:
            query += " AND a.office_id = ?"
            params.append(user['office_id'])

        if filter_office:
            query += " AND a.office_id = ?"
            params.append(filter_office)

        if filter_type:
            query += " AND a.type = ?"
            params.append(filter_type)

        if filter_status:
            query += " AND a.status = ?"
            params.append(filter_status)

        query += " ORDER BY a.assignment_no DESC"

        cursor.execute(query, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get offices for filter dropdown
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
            "assignments": assignments,
            "offices": offices,
            "statuses": statuses,
            "filter_office": filter_office,
            "filter_type": filter_type,
            "filter_status": filter_status,
            "show_all": show_all
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
