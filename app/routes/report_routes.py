"""
Routes for Delay Tracking (3C), Physical Progress MIS (3D), Financial Progress MIS (3E).
These reports are designed to sit on top of the dashboard as key tracking metrics.
Revenue recognized on case basis, expenditure on accrual basis.
"""
from datetime import date, datetime

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import get_db, USE_POSTGRES, get_current_fy
from app.dependencies import get_current_user
from app.templates_config import templates

router = APIRouter()


def _date_diff_sql(column):
    """SQL expression for days since a date column."""
    if USE_POSTGRES:
        return f"(CURRENT_DATE - {column}::date)"
    return f"CAST(julianday('now') - julianday({column}) AS INTEGER)"


def _traffic_light(days):
    """Return traffic light color based on delay days."""
    if days < 30:
        return 'green'
    elif days < 60:
        return 'amber'
    return 'red'


# ─────────────────────────────────────────────
# 1. Delay Tracking Dashboard
# ─────────────────────────────────────────────

@router.get("/delays", response_class=HTMLResponse)
async def delay_dashboard(request: Request, office: str = None, domain: str = None):
    """Main delay tracking dashboard with 4 delay categories."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from fastapi.responses import RedirectResponse

    with get_db() as conn:
        cursor = conn.cursor()

        office_filter = ""
        office_params = []
        if office:
            office_filter = "AND a.office_id = ?"
            office_params = [office]

        # A. Payment Delays: invoices approved but no payment received
        cursor.execute(f"""
            SELECT ir.id, ir.request_number, ir.invoice_amount, ir.status,
                   ir.approved_at, a.assignment_no, a.title, a.office_id,
                   {_date_diff_sql('ir.approved_at')} as delay_days
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            LEFT JOIN payment_receipts pr ON ir.id = pr.invoice_request_id
            WHERE ir.status IN ('APPROVED', 'INVOICED')
            AND pr.id IS NULL
            AND ir.approved_at IS NOT NULL
            {office_filter}
            ORDER BY delay_days DESC
        """, office_params)
        payment_delays = cursor.fetchall()

        # B. Invoice Delays: milestones past target_date but invoice not raised
        cursor.execute(f"""
            SELECT m.id, m.milestone_no, m.title as milestone_title, m.target_date,
                   m.invoice_percent, a.assignment_no, a.title, a.office_id,
                   {_date_diff_sql('m.target_date')} as delay_days
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.target_date < DATE('now')
            AND m.invoice_raised = 0
            AND m.status != 'Cancelled'
            {office_filter}
            ORDER BY delay_days DESC
        """, office_params)
        invoice_delays = cursor.fetchall()

        # C. Milestone Delays: past target_date but not completed
        cursor.execute(f"""
            SELECT m.id, m.milestone_no, m.title as milestone_title, m.target_date,
                   m.status, m.invoice_percent, a.assignment_no, a.title, a.office_id,
                   {_date_diff_sql('m.target_date')} as delay_days
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.target_date < DATE('now')
            AND m.status NOT IN ('Completed', 'Cancelled')
            {office_filter}
            ORDER BY delay_days DESC
        """, office_params)
        milestone_delays = cursor.fetchall()

        # D. Activation Delays: stuck in early workflow stages > 30 days
        cursor.execute(f"""
            SELECT a.id, a.assignment_no, a.title, a.office_id, a.workflow_stage,
                   a.created_at, {_date_diff_sql('a.created_at')} as delay_days
            FROM assignments a
            WHERE a.workflow_stage IN ('REGISTRATION', 'TL_ASSIGNMENT', 'DETAIL_ENTRY')
            AND {_date_diff_sql('a.created_at')} > 30
            {office_filter}
            ORDER BY delay_days DESC
        """, office_params)
        activation_delays = cursor.fetchall()

        # Get offices and domains for filters
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = cursor.fetchall()

    return templates.TemplateResponse("report_delays.html", {
        "request": request, "user": user,
        "payment_delays": payment_delays,
        "invoice_delays": invoice_delays,
        "milestone_delays": milestone_delays,
        "activation_delays": activation_delays,
        "filter_office": office, "filter_domain": domain,
        "offices": offices,
        "traffic_light": _traffic_light,
    })


# ─────────────────────────────────────────────
# 2. Delay Summary API (for dashboard cards)
# ─────────────────────────────────────────────

@router.get("/delays/api/summary")
async def delay_summary_api(request: Request, office: str = None):
    """JSON API for delay summary counts."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    with get_db() as conn:
        cursor = conn.cursor()
        office_filter = ""
        params = []
        if office:
            office_filter = "AND a.office_id = ?"
            params = [office]

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            LEFT JOIN payment_receipts pr ON ir.id = pr.invoice_request_id
            WHERE ir.status IN ('APPROVED','INVOICED') AND pr.id IS NULL {office_filter}
        """, params)
        payment_delays = cursor.fetchone()['cnt']

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.target_date < DATE('now') AND m.invoice_raised = 0
            AND m.status != 'Cancelled' {office_filter}
        """, params)
        invoice_delays = cursor.fetchone()['cnt']

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.target_date < DATE('now')
            AND m.status NOT IN ('Completed','Cancelled') {office_filter}
        """, params)
        milestone_delays = cursor.fetchone()['cnt']

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM assignments a
            WHERE a.workflow_stage IN ('REGISTRATION','TL_ASSIGNMENT','DETAIL_ENTRY')
            AND {_date_diff_sql('a.created_at')} > 30 {office_filter}
        """, params)
        activation_delays = cursor.fetchone()['cnt']

    return JSONResponse(content={
        "payment_delays": payment_delays,
        "invoice_delays": invoice_delays,
        "milestone_delays": milestone_delays,
        "activation_delays": activation_delays,
        "total": payment_delays + invoice_delays + milestone_delays + activation_delays,
    })


# ─────────────────────────────────────────────
# 3. Physical Progress MIS
# ─────────────────────────────────────────────

@router.get("/physical-progress", response_class=HTMLResponse)
async def physical_progress(request: Request, view: str = "office", office: str = None, type: str = None):
    """Physical progress report by office/domain/officer/type."""
    user = get_current_user(request)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        type_filter = ""
        type_params = []
        if type:
            type_filter = "AND a.type = ?"
            type_params = [type]

        if view == 'office':
            cursor.execute(f"""
                SELECT off.office_id, off.office_name,
                       COUNT(a.id) as total_assignments,
                       AVG(a.physical_progress_percent) as avg_physical_progress,
                       AVG(a.timeline_progress_percent) as avg_timeline_progress,
                       SUM(CASE WHEN a.status = 'Completed' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN a.status IN ('Ongoing','In Progress','Not Started') THEN 1 ELSE 0 END) as active,
                       (SELECT COUNT(*) FROM milestones m2 JOIN assignments a2 ON m2.assignment_id = a2.id
                        WHERE a2.office_id = off.office_id) as total_milestones,
                       (SELECT COUNT(*) FROM milestones m2 JOIN assignments a2 ON m2.assignment_id = a2.id
                        WHERE a2.office_id = off.office_id AND m2.status = 'Completed') as completed_milestones,
                       (SELECT COUNT(*) FROM milestones m2 JOIN assignments a2 ON m2.assignment_id = a2.id
                        WHERE a2.office_id = off.office_id AND m2.target_date < DATE('now')
                        AND m2.status NOT IN ('Completed','Cancelled')) as delayed_milestones
                FROM offices off
                LEFT JOIN assignments a ON off.office_id = a.office_id {type_filter}
                GROUP BY off.office_id, off.office_name
                HAVING total_assignments > 0
                ORDER BY avg_physical_progress DESC
            """, type_params)

        elif view == 'domain':
            cursor.execute(f"""
                SELECT a.domain,
                       COUNT(a.id) as total_assignments,
                       AVG(a.physical_progress_percent) as avg_physical_progress,
                       AVG(a.timeline_progress_percent) as avg_timeline_progress,
                       SUM(CASE WHEN a.status = 'Completed' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN a.status IN ('Ongoing','In Progress','Not Started') THEN 1 ELSE 0 END) as active
                FROM assignments a
                WHERE a.domain IS NOT NULL {type_filter}
                GROUP BY a.domain
                ORDER BY avg_physical_progress DESC
            """, type_params)

        elif view == 'officer':
            cursor.execute(f"""
                SELECT o.officer_id, o.name as officer_name, o.office_id,
                       COUNT(DISTINCT a.id) as total_assignments,
                       AVG(a.physical_progress_percent) as avg_physical_progress,
                       SUM(CASE WHEN a.status = 'Completed' THEN 1 ELSE 0 END) as completed
                FROM officers o
                JOIN revenue_shares rs ON o.officer_id = rs.officer_id
                JOIN assignments a ON rs.assignment_id = a.id {type_filter}
                GROUP BY o.officer_id, o.name, o.office_id
                ORDER BY avg_physical_progress DESC
            """, type_params)

        else:  # by assignment type
            cursor.execute("""
                SELECT a.type,
                       COUNT(a.id) as total_assignments,
                       AVG(a.physical_progress_percent) as avg_physical_progress,
                       AVG(a.timeline_progress_percent) as avg_timeline_progress,
                       SUM(CASE WHEN a.status = 'Completed' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN a.status IN ('Ongoing','In Progress','Not Started') THEN 1 ELSE 0 END) as active
                FROM assignments a
                WHERE a.type IS NOT NULL
                GROUP BY a.type
            """)

        progress_data = cursor.fetchall()

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = cursor.fetchall()

    return templates.TemplateResponse("report_physical_progress.html", {
        "request": request, "user": user, "progress_data": progress_data,
        "view": view, "filter_office": office, "filter_type": type,
        "offices": offices,
    })


@router.get("/physical-progress/api/data")
async def physical_progress_api(request: Request, office: str = None):
    """JSON API for physical progress chart data."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    with get_db() as conn:
        cursor = conn.cursor()
        params = []
        office_filter = ""
        if office:
            office_filter = "WHERE a.office_id = ?"
            params = [office]

        cursor.execute(f"""
            SELECT a.status, COUNT(*) as count,
                   AVG(a.physical_progress_percent) as avg_progress
            FROM assignments a {office_filter}
            GROUP BY a.status
        """, params)
        by_status = [{"status": r['status'], "count": r['count'],
                      "avg_progress": round(r['avg_progress'] or 0, 1)} for r in cursor.fetchall()]

    return JSONResponse(content={"by_status": by_status})


# ─────────────────────────────────────────────
# 5. Financial Progress MIS
# ─────────────────────────────────────────────

@router.get("/financial-progress", response_class=HTMLResponse)
async def financial_progress(request: Request, view: str = "office",
                             fy: str = None, office: str = None):
    """Financial progress report. Revenue on case basis, expenditure on accrual basis."""
    user = get_current_user(request)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=302)

    if not fy:
        fy = get_current_fy()

    with get_db() as conn:
        cursor = conn.cursor()

        if view == 'office':
            cursor.execute("""
                SELECT off.office_id, off.office_name,
                       COALESCE(SUM(a.total_value), 0) as total_value,
                       COALESCE(SUM(a.invoice_amount), 0) as total_invoiced,
                       COALESCE(SUM(a.amount_received), 0) as total_received,
                       COALESCE(SUM(a.total_expenditure), 0) as total_expenditure,
                       COALESCE(SUM(a.amount_received - a.total_expenditure), 0) as net_revenue,
                       COALESCE(SUM(a.surplus_deficit), 0) as surplus_deficit,
                       COUNT(a.id) as assignment_count
                FROM offices off
                LEFT JOIN assignments a ON off.office_id = a.office_id
                GROUP BY off.office_id, off.office_name
                HAVING assignment_count > 0
                ORDER BY total_value DESC
            """)

        elif view == 'domain':
            cursor.execute("""
                SELECT a.domain,
                       COALESCE(SUM(a.total_value), 0) as total_value,
                       COALESCE(SUM(a.invoice_amount), 0) as total_invoiced,
                       COALESCE(SUM(a.amount_received), 0) as total_received,
                       COALESCE(SUM(a.total_expenditure), 0) as total_expenditure,
                       COALESCE(SUM(a.amount_received - a.total_expenditure), 0) as net_revenue,
                       COUNT(a.id) as assignment_count
                FROM assignments a
                WHERE a.domain IS NOT NULL
                GROUP BY a.domain
                ORDER BY total_value DESC
            """)

        else:  # by type
            cursor.execute("""
                SELECT a.type,
                       COALESCE(SUM(a.total_value), 0) as total_value,
                       COALESCE(SUM(a.invoice_amount), 0) as total_invoiced,
                       COALESCE(SUM(a.amount_received), 0) as total_received,
                       COALESCE(SUM(a.total_expenditure), 0) as total_expenditure,
                       COALESCE(SUM(a.amount_received - a.total_expenditure), 0) as net_revenue,
                       COUNT(a.id) as assignment_count
                FROM assignments a
                WHERE a.type IS NOT NULL
                GROUP BY a.type
            """)

        financial_data = cursor.fetchall()

        # Expenditure breakdown by category (accrual basis - by entry_date)
        cursor.execute("""
            SELECT eh.category, eh.head_name,
                   COALESCE(SUM(ei.estimated_amount), 0) as budgeted,
                   COALESCE(SUM(ee.amount), 0) as actual_spent
            FROM expenditure_heads eh
            LEFT JOIN expenditure_items ei ON eh.id = ei.head_id
            LEFT JOIN expenditure_entries ee ON ei.id = ee.expenditure_item_id
            GROUP BY eh.category, eh.head_name
            HAVING budgeted > 0 OR actual_spent > 0
            ORDER BY eh.category
        """)
        expenditure_breakdown = cursor.fetchall()

        # Grand totals
        cursor.execute("""
            SELECT COALESCE(SUM(total_value), 0) as grand_value,
                   COALESCE(SUM(invoice_amount), 0) as grand_invoiced,
                   COALESCE(SUM(amount_received), 0) as grand_received,
                   COALESCE(SUM(total_expenditure), 0) as grand_expenditure,
                   COALESCE(SUM(amount_received - total_expenditure), 0) as grand_net
            FROM assignments
        """)
        totals = cursor.fetchone()

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = cursor.fetchall()

    return templates.TemplateResponse("report_financial_progress.html", {
        "request": request, "user": user, "financial_data": financial_data,
        "expenditure_breakdown": expenditure_breakdown,
        "totals": totals, "view": view, "fy": fy,
        "filter_office": office, "offices": offices,
    })


@router.get("/financial-progress/api/data")
async def financial_progress_api(request: Request, office: str = None, fy: str = None):
    """JSON API for financial progress chart data."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if not fy:
        fy = get_current_fy()

    with get_db() as conn:
        cursor = conn.cursor()
        params = []
        office_filter = ""
        if office:
            office_filter = "WHERE a.office_id = ?"
            params = [office]

        cursor.execute(f"""
            SELECT COALESCE(SUM(a.total_value), 0) as total_value,
                   COALESCE(SUM(a.invoice_amount), 0) as invoiced,
                   COALESCE(SUM(a.amount_received), 0) as received,
                   COALESCE(SUM(a.total_expenditure), 0) as expenditure,
                   COALESCE(SUM(a.amount_received - a.total_expenditure), 0) as net
            FROM assignments a {office_filter}
        """, params)
        row = cursor.fetchone()

    return JSONResponse(content={
        "total_value": round(row['total_value'] or 0, 2),
        "invoiced": round(row['invoiced'] or 0, 2),
        "received": round(row['received'] or 0, 2),
        "expenditure": round(row['expenditure'] or 0, 2),
        "net": round(row['net'] or 0, 2),
        "surplus_deficit": round((row['received'] or 0) - (row['expenditure'] or 0), 2),
    })


# ─────────────────────────────────────────────
# 7. Dashboard Summary API (embed on main dashboard)
# ─────────────────────────────────────────────

@router.get("/api/dashboard-summary")
async def dashboard_summary_api(request: Request, office: str = None):
    """Key tracking metrics for embedding on top of main dashboard."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    with get_db() as conn:
        cursor = conn.cursor()
        params = []
        of = ""
        if office:
            of = "AND a.office_id = ?"
            params = [office]

        # Delay counts
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            LEFT JOIN payment_receipts pr ON ir.id = pr.invoice_request_id
            WHERE ir.status IN ('APPROVED','INVOICED') AND pr.id IS NULL {of}
        """, params)
        payment_delays = cursor.fetchone()['cnt']

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.target_date < DATE('now') AND m.invoice_raised = 0
            AND m.status != 'Cancelled' {of}
        """, params)
        invoice_delays = cursor.fetchone()['cnt']

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.target_date < DATE('now')
            AND m.status NOT IN ('Completed','Cancelled') {of}
        """, params)
        milestone_delays = cursor.fetchone()['cnt']

        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM assignments a
            WHERE a.workflow_stage IN ('REGISTRATION','TL_ASSIGNMENT','DETAIL_ENTRY')
            AND {_date_diff_sql('a.created_at')} > 30 {of}
        """, params)
        activation_delays = cursor.fetchone()['cnt']

        # Physical progress
        of2 = ""
        params2 = []
        if office:
            of2 = "WHERE a.office_id = ?"
            params2 = [office]

        cursor.execute(f"""
            SELECT AVG(a.physical_progress_percent) as avg_pct,
                   SUM(CASE WHEN a.physical_progress_percent >= 80 THEN 1 ELSE 0 END) as on_track,
                   SUM(CASE WHEN a.physical_progress_percent < 50 AND a.status NOT IN ('Completed','Cancelled')
                       THEN 1 ELSE 0 END) as delayed,
                   SUM(CASE WHEN a.status = 'Completed' THEN 1 ELSE 0 END) as completed
            FROM assignments a {of2}
        """, params2)
        phys = cursor.fetchone()

        # Financial summary
        cursor.execute(f"""
            SELECT COALESCE(SUM(a.total_value), 0) as total_value,
                   COALESCE(SUM(a.invoice_amount), 0) as invoiced,
                   COALESCE(SUM(a.amount_received), 0) as received,
                   COALESCE(SUM(a.total_expenditure), 0) as expenditure
            FROM assignments a {of2}
        """, params2)
        fin = cursor.fetchone()

    return JSONResponse(content={
        "delays": {
            "payment": payment_delays, "invoice": invoice_delays,
            "milestone": milestone_delays, "activation": activation_delays,
        },
        "physical_progress": {
            "avg_percent": round(phys['avg_pct'] or 0, 1),
            "on_track": phys['on_track'] or 0,
            "delayed": phys['delayed'] or 0,
            "completed": phys['completed'] or 0,
        },
        "financial": {
            "total_value": round(fin['total_value'] or 0, 2),
            "invoiced": round(fin['invoiced'] or 0, 2),
            "received": round(fin['received'] or 0, 2),
            "expenditure": round(fin['expenditure'] or 0, 2),
            "net": round((fin['received'] or 0) - (fin['expenditure'] or 0), 2),
            "surplus_deficit": round((fin['received'] or 0) - (fin['expenditure'] or 0), 2),
        }
    })
