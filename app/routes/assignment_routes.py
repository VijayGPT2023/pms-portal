"""
Assignment routes: view, create, update assignment details.
"""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user
from app.config import ASSIGNMENT_STATUS_OPTIONS, CLIENT_TYPE_OPTIONS, DOMAIN_OPTIONS
from app.templates_config import templates

router = APIRouter()


def get_config_options(category: str):
    """Get configuration options from database."""
    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute("""
                SELECT option_value, option_label FROM config_options
                WHERE category = %s AND is_active = 1
                ORDER BY sort_order
            """, (category,))
        else:
            cursor.execute("""
                SELECT option_value, option_label FROM config_options
                WHERE category = ? AND is_active = 1
                ORDER BY sort_order
            """, (category,))
        options = [dict(row) for row in cursor.fetchall()]
        # Fallback to hardcoded values if no DB options
        if not options:
            if category == 'domain':
                return [{'option_value': d, 'option_label': d} for d in DOMAIN_OPTIONS]
            elif category == 'client_type':
                return [{'option_value': c, 'option_label': c} for c in CLIENT_TYPE_OPTIONS]
            elif category == 'status':
                return [{'option_value': s, 'option_label': s} for s in ASSIGNMENT_STATUS_OPTIONS]
        return options


def get_offices_list():
    """Get list of all offices."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT office_id FROM offices ORDER BY office_id")
        return [row['office_id'] for row in cursor.fetchall()]


def get_officers_list():
    """Get list of all officers for dropdowns."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers
            WHERE is_active = 1
            ORDER BY name
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_assignment(assignment_id: int):
    """Get assignment by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute("SELECT * FROM assignments WHERE id = %s", (assignment_id,))
        else:
            cursor.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


# ============================================================
# Registration Workflow (Step 1): Any officer registers new activity
# ============================================================

@router.get("/register", response_class=HTMLResponse)
async def register_activity_page(request: Request):
    """Display minimal registration form for any officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    error = request.query_params.get('error', '')
    return templates.TemplateResponse(
        "register_activity.html",
        {
            "request": request,
            "user": user,
            "error": error
        }
    )


@router.post("/register")
async def register_activity_submit(request: Request):
    """Create a minimal assignment registration and submit for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form_data = await request.form()
    title = form_data.get('title', '').strip()
    activity_type = form_data.get('type', 'ASSIGNMENT')
    client = form_data.get('client', '').strip()
    description = form_data.get('description', '').strip()

    if not title:
        return RedirectResponse(url="/assignment/register?error=Title is required", status_code=302)

    if activity_type not in ('ASSIGNMENT', 'TRAINING', 'DEVELOPMENT'):
        activity_type = 'ASSIGNMENT'

    office_id = user['office_id']
    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        # Generate assignment number
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_no FROM assignments
                WHERE office_id = %s AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM CURRENT_DATE)
            """, (office_id,))
        else:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_no FROM assignments
                WHERE office_id = ? AND strftime('%Y', created_at) = strftime('%Y', 'now')
            """, (office_id,))
        next_no = cursor.fetchone()['next_no']

        import datetime
        year = datetime.datetime.now().year
        assignment_no = f"{office_id}/{year}/{next_no:03d}"

        # Insert minimal assignment with workflow state
        cursor.execute(f"""
            INSERT INTO assignments
            (assignment_no, type, title, client, tor_scope, office_id, status,
             registered_by, registration_status, workflow_stage, approval_status)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'Pipeline',
                    {ph}, 'PENDING_APPROVAL', 'REGISTRATION', 'DRAFT')
        """, (
            assignment_no,
            activity_type,
            title,
            client,
            description,
            office_id,
            user['officer_id']
        ))

        # Get the new assignment ID
        if USE_POSTGRES:
            cursor.execute("SELECT lastval() as id")
            assignment_id = cursor.fetchone()['id']
        else:
            assignment_id = cursor.lastrowid

        # Create approval request for Head
        cursor.execute(f"""
            INSERT INTO approval_requests
            (request_type, reference_type, reference_id, requested_by, office_id, status, request_data, remarks)
            VALUES ('REGISTRATION', 'assignment', {ph}, {ph}, {ph}, 'PENDING', {ph}, {ph})
        """, (
            assignment_id,
            user['officer_id'],
            office_id,
            f'{{"title": "{title}", "type": "{activity_type}", "client": "{client}"}}',
            f'New {activity_type.lower()} registration by {user["name"]}'
        ))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'CREATE', 'assignment', {ph}, {ph})
        """, (user['officer_id'], assignment_id, f'Registered new {activity_type.lower()}: {title}'))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?registered=1", status_code=302)


@router.get("/workorders", response_class=HTMLResponse)
async def workorders_list(request: Request):
    """Display Work Orders list."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    filter_view = request.query_params.get('view', '')
    filter_office = request.query_params.get('office', '')
    filter_status = request.query_params.get('status', '')

    with get_db() as conn:
        cursor = conn.cursor()

        # Base query for work orders (assignments)
        query = """
            SELECT a.*,
                   o.name as team_leader_name,
                   off.office_name
            FROM assignments a
            LEFT JOIN officers o ON a.team_leader_officer_id = o.officer_id
            LEFT JOIN offices off ON a.office_id = off.office_id
            WHERE 1=1
        """
        params = []

        # Apply filters - use correct placeholder for database type
        ph = '%s' if USE_POSTGRES else '?'
        if filter_view == 'my_created':
            query += f" AND a.team_leader_officer_id = {ph}"
            params.append(user['officer_id'])
        elif filter_view == 'my_office':
            query += f" AND a.office_id = {ph}"
            params.append(user['office_id'])

        if filter_office:
            query += f" AND a.office_id = {ph}"
            params.append(filter_office)

        if filter_status:
            query += f" AND a.status = {ph}"
            params.append(filter_status)

        query += " ORDER BY a.created_at DESC"

        cursor.execute(query, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get status counts
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM assignments
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Get offices for filter
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "workorders_list.html",
        {
            "request": request,
            "user": user,
            "assignments": assignments,
            "status_counts": status_counts,
            "offices": offices,
            "filter_view": filter_view,
            "filter_office": filter_office,
            "filter_status": filter_status
        }
    )


@router.get("/select-type/{assignment_id}", response_class=HTMLResponse)
async def select_type_page(request: Request, assignment_id: int):
    """Display type selection page for an assignment."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    # If type is already set, redirect to the appropriate form
    if assignment['type']:
        return RedirectResponse(url=f"/assignment/edit/{assignment_id}", status_code=302)

    return templates.TemplateResponse(
        "select_type.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment
        }
    )


@router.post("/select-type/{assignment_id}")
async def select_type_submit(request: Request, assignment_id: int, assignment_type: str = Form(...)):
    """Handle type selection form submission."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE assignments SET type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (assignment_type, assignment_id)
        )

    return RedirectResponse(url=f"/assignment/edit/{assignment_id}", status_code=302)


@router.get("/edit/{assignment_id}", response_class=HTMLResponse)
async def edit_assignment_page(request: Request, assignment_id: int):
    """Display assignment edit form based on type."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    # If type is not set, redirect to type selection
    if not assignment['type']:
        return RedirectResponse(url=f"/assignment/select-type/{assignment_id}", status_code=302)

    officers = get_officers_list()

    if assignment['type'] == 'ASSIGNMENT':
        template_name = "assignment_form.html"
    elif assignment['type'] == 'DEVELOPMENT':
        template_name = "development_form.html"
    else:
        template_name = "training_form.html"

    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "officers": officers,
            "status_options": ASSIGNMENT_STATUS_OPTIONS,
            "client_type_options": CLIENT_TYPE_OPTIONS,
            "domain_options": DOMAIN_OPTIONS,
            "is_edit": True
        }
    )


@router.post("/edit/{assignment_id}")
async def edit_assignment_submit(
    request: Request,
    assignment_id: int,
    title: str = Form(...),
    status: str = Form(...),
    # Assignment-specific fields
    tor_scope: Optional[str] = Form(None),
    client: Optional[str] = Form(None),
    client_type: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    domain: Optional[str] = Form(None),
    work_order_date: Optional[str] = Form(None),
    start_date: Optional[str] = Form(None),
    target_date: Optional[str] = Form(None),
    team_leader_officer_id: Optional[str] = Form(None),
    # Training-specific fields
    venue: Optional[str] = Form(None),
    duration_start: Optional[str] = Form(None),
    duration_end: Optional[str] = Form(None),
    duration_days: Optional[int] = Form(None),
    type_of_participants: Optional[str] = Form(None),
    faculty1_officer_id: Optional[str] = Form(None),
    faculty2_officer_id: Optional[str] = Form(None),
    # Development-specific fields
    man_days: Optional[float] = Form(None),
    daily_rate: Optional[float] = Form(None)
):
    """Handle assignment edit form submission."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Reset basic info approval if it was previously approved (re-approval needed)
        reset_clause = ""
        if assignment.get('approval_status') == 'APPROVED':
            reset_clause = ", approval_status = 'SUBMITTED'"

        if assignment['type'] == 'ASSIGNMENT':
            cursor.execute(f"""
                UPDATE assignments SET
                    title = ?,
                    tor_scope = ?,
                    client = ?,
                    client_type = ?,
                    city = ?,
                    domain = ?,
                    work_order_date = ?,
                    start_date = ?,
                    target_date = ?,
                    team_leader_officer_id = ?,
                    status = ?,
                    details_filled = 1
                    {reset_clause},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                title,
                tor_scope,
                client,
                client_type,
                city,
                domain,
                work_order_date if work_order_date else None,
                start_date if start_date else None,
                target_date if target_date else None,
                team_leader_officer_id if team_leader_officer_id else None,
                status,
                assignment_id
            ))
        elif assignment['type'] == 'DEVELOPMENT':
            man_days_val = man_days or 0
            daily_rate_val = 0.20  # 20k per day = 0.20 Lakhs
            total_value = man_days_val * daily_rate_val

            cursor.execute(f"""
                UPDATE assignments SET
                    title = ?,
                    tor_scope = ?,
                    client = ?,
                    man_days = ?,
                    daily_rate = ?,
                    is_notional = 1,
                    total_value = ?,
                    gross_value = ?,
                    start_date = ?,
                    target_date = ?,
                    team_leader_officer_id = ?,
                    status = ?,
                    details_filled = 1
                    {reset_clause},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                title,
                tor_scope,
                client,
                man_days_val,
                daily_rate_val,
                total_value,
                total_value,
                start_date if start_date else None,
                target_date if target_date else None,
                team_leader_officer_id if team_leader_officer_id else None,
                status,
                assignment_id
            ))
        else:  # TRAINING
            cursor.execute(f"""
                UPDATE assignments SET
                    title = ?,
                    venue = ?,
                    duration_start = ?,
                    duration_end = ?,
                    duration_days = ?,
                    type_of_participants = ?,
                    faculty1_officer_id = ?,
                    faculty2_officer_id = ?,
                    status = ?,
                    details_filled = 1
                    {reset_clause},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                title,
                venue,
                duration_start if duration_start else None,
                duration_end if duration_end else None,
                duration_days,
                type_of_participants,
                faculty1_officer_id if faculty1_officer_id else None,
                faculty2_officer_id if faculty2_officer_id else None,
                status,
                assignment_id
            ))

    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/view/{assignment_id}", response_class=HTMLResponse)
async def view_assignment(request: Request, assignment_id: int):
    """View assignment details with tabbed interface."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    active_tab = request.query_params.get('tab', 'basic')
    if active_tab not in ('basic', 'milestones', 'cost', 'team'):
        active_tab = 'basic'

    # Cost tab period filter: 'all' (till date) or FY string like '2025-26'
    cost_period = request.query_params.get('cost_period', 'all')

    PH = '%s' if USE_POSTGRES else '?'

    # Always load officer names for header
    officers = {}
    milestones = []
    revenue_shares = []
    expenditure_items = []
    expenditure_entries = []
    expenditure_heads = []

    with get_db() as conn:
        cursor = conn.cursor()

        # Officer names (needed for basic tab header)
        for field in ['team_leader_officer_id', 'faculty1_officer_id', 'faculty2_officer_id']:
            if assignment.get(field):
                cursor.execute(f"SELECT name FROM officers WHERE officer_id = {PH}", (assignment[field],))
                row = cursor.fetchone()
                if row:
                    officers[field] = row['name']

        # Tab-specific data loading
        if active_tab == 'basic':
            # Load milestones summary count and revenue shares count for progress bar
            cursor.execute(f"SELECT COUNT(*) as cnt FROM milestones WHERE assignment_id = {PH}", (assignment_id,))
            milestone_count = cursor.fetchone()['cnt']
            cursor.execute(f"SELECT COUNT(*) as cnt FROM revenue_shares WHERE assignment_id = {PH}", (assignment_id,))
            revenue_count = cursor.fetchone()['cnt']

        elif active_tab == 'milestones':
            cursor.execute(f"""
                SELECT * FROM milestones
                WHERE assignment_id = {PH}
                ORDER BY milestone_no
            """, (assignment_id,))
            milestones = [dict(row) for row in cursor.fetchall()]

        elif active_tab == 'cost':
            # Load expenditure heads and items (always till-date for estimates)
            cursor.execute("SELECT * FROM expenditure_heads ORDER BY category, head_code")
            expenditure_heads = [dict(row) for row in cursor.fetchall()]

            cursor.execute(f"""
                SELECT ei.*, eh.head_code, eh.head_name, eh.category
                FROM expenditure_items ei
                JOIN expenditure_heads eh ON ei.head_id = eh.id
                WHERE ei.assignment_id = {PH}
                ORDER BY eh.category, eh.head_code
            """, (assignment_id,))
            expenditure_items = [dict(row) for row in cursor.fetchall()]

            # Load date-wise expenditure entries (filtered by period)
            if cost_period and cost_period != 'all':
                cursor.execute(f"""
                    SELECT ee.*, eh.head_code, eh.head_name, o.name as entered_by_name
                    FROM expenditure_entries ee
                    JOIN expenditure_heads eh ON ee.head_id = eh.id
                    LEFT JOIN officers o ON ee.entered_by = o.officer_id
                    WHERE ee.assignment_id = {PH} AND ee.fy_period = {PH}
                    ORDER BY ee.entry_date DESC
                """, (assignment_id, cost_period))
            else:
                cursor.execute(f"""
                    SELECT ee.*, eh.head_code, eh.head_name, o.name as entered_by_name
                    FROM expenditure_entries ee
                    JOIN expenditure_heads eh ON ee.head_id = eh.id
                    LEFT JOIN officers o ON ee.entered_by = o.officer_id
                    WHERE ee.assignment_id = {PH}
                    ORDER BY ee.entry_date DESC
                """, (assignment_id,))
            expenditure_entries = [dict(row) for row in cursor.fetchall()]

            # Get available FY periods for this assignment's entries
            cursor.execute(f"""
                SELECT DISTINCT fy_period FROM expenditure_entries
                WHERE assignment_id = {PH}
                ORDER BY fy_period
            """, (assignment_id,))
            available_fys = [row['fy_period'] for row in cursor.fetchall()]

        elif active_tab == 'team':
            cursor.execute(f"""
                SELECT rs.*, o.name as officer_name, o.designation, o.office_id as officer_office
                FROM revenue_shares rs
                JOIN officers o ON rs.officer_id = o.officer_id
                WHERE rs.assignment_id = {PH}
                ORDER BY rs.share_percent DESC
            """, (assignment_id,))
            revenue_shares = [dict(row) for row in cursor.fetchall()]

    context = {
        "request": request,
        "user": user,
        "assignment": assignment,
        "officers": officers,
        "active_tab": active_tab,
        "milestones": milestones,
        "revenue_shares": revenue_shares,
        "expenditure_items": expenditure_items,
        "expenditure_entries": expenditure_entries,
        "expenditure_heads": expenditure_heads,
    }

    if active_tab == 'basic':
        context["milestone_count"] = milestone_count
        context["revenue_count"] = revenue_count
    elif active_tab == 'cost':
        context["cost_period"] = cost_period
        context["available_fys"] = available_fys

    return templates.TemplateResponse("assignment_view.html", context)


@router.get("/milestones/{assignment_id}", response_class=HTMLResponse)
async def manage_milestones(request: Request, assignment_id: int):
    """Display milestone management page."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute("""
                SELECT * FROM milestones
                WHERE assignment_id = %s
                ORDER BY milestone_no
            """, (assignment_id,))
        else:
            cursor.execute("""
                SELECT * FROM milestones
                WHERE assignment_id = ?
                ORDER BY milestone_no
            """, (assignment_id,))
        milestones = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "milestones_form.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "milestones": milestones
        }
    )


@router.post("/milestones/{assignment_id}")
async def save_milestones(request: Request, assignment_id: int):
    """Save milestone updates."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    form_data = await request.form()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get existing milestones
        if USE_POSTGRES:
            cursor.execute("SELECT id FROM milestones WHERE assignment_id = %s", (assignment_id,))
        else:
            cursor.execute("SELECT id FROM milestones WHERE assignment_id = ?", (assignment_id,))
        existing_ids = {row['id'] for row in cursor.fetchall()}

        # Process form data - milestones are submitted as milestone_X_field
        milestone_data = {}
        for key, value in form_data.items():
            if key.startswith('milestone_'):
                parts = key.split('_')
                if len(parts) >= 3:
                    idx = parts[1]
                    field = '_'.join(parts[2:])
                    if idx not in milestone_data:
                        milestone_data[idx] = {}
                    milestone_data[idx][field] = value

        processed_ids = set()

        for idx, data in milestone_data.items():
            milestone_id = data.get('id')
            title = data.get('title', '').strip()

            if not title:
                continue  # Skip empty milestones

            invoice_raised = 1 if data.get('invoice_raised') else 0
            payment_received = 1 if data.get('payment_received') else 0

            if milestone_id and milestone_id.isdigit():
                # Update existing milestone
                milestone_id = int(milestone_id)
                processed_ids.add(milestone_id)
                if USE_POSTGRES:
                    cursor.execute("""
                        UPDATE milestones SET
                            title = %s,
                            description = %s,
                            target_date = %s,
                            revenue_percent = %s,
                            invoice_raised = %s,
                            invoice_raised_date = %s,
                            payment_received = %s,
                            payment_received_date = %s,
                            status = %s,
                            remarks = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (
                        title,
                        data.get('description', ''),
                        data.get('target_date') or None,
                        float(data.get('revenue_percent', 0) or 0),
                        invoice_raised,
                        data.get('invoice_raised_date') or None,
                        payment_received,
                        data.get('payment_received_date') or None,
                        data.get('status', 'Pending'),
                        data.get('remarks', ''),
                        milestone_id
                    ))
                else:
                    cursor.execute("""
                        UPDATE milestones SET
                            title = ?,
                            description = ?,
                            target_date = ?,
                            revenue_percent = ?,
                            invoice_raised = ?,
                            invoice_raised_date = ?,
                            payment_received = ?,
                            payment_received_date = ?,
                            status = ?,
                            remarks = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        title,
                        data.get('description', ''),
                        data.get('target_date') or None,
                        float(data.get('revenue_percent', 0) or 0),
                        invoice_raised,
                        data.get('invoice_raised_date') or None,
                        payment_received,
                        data.get('payment_received_date') or None,
                        data.get('status', 'Pending'),
                        data.get('remarks', ''),
                        milestone_id
                    ))
            else:
                # Insert new milestone
                if USE_POSTGRES:
                    cursor.execute("SELECT COALESCE(MAX(milestone_no), 0) + 1 FROM milestones WHERE assignment_id = %s",
                                 (assignment_id,))
                else:
                    cursor.execute("SELECT COALESCE(MAX(milestone_no), 0) + 1 FROM milestones WHERE assignment_id = ?",
                                 (assignment_id,))
                next_no = cursor.fetchone()[0]

                target_date = data.get('target_date') or None
                if USE_POSTGRES:
                    cursor.execute("""
                        INSERT INTO milestones
                        (assignment_id, milestone_no, title, description, target_date, tentative_date,
                         tentative_date_status, revenue_percent,
                         invoice_raised, invoice_raised_date, payment_received, payment_received_date,
                         status, remarks)
                        VALUES (%s, %s, %s, %s, %s, %s, 'APPROVED', %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        assignment_id,
                        next_no,
                        title,
                        data.get('description', ''),
                        target_date,
                        target_date,  # tentative_date defaults to target_date
                        float(data.get('revenue_percent', 0) or 0),
                        invoice_raised,
                        data.get('invoice_raised_date') or None,
                        payment_received,
                        data.get('payment_received_date') or None,
                        data.get('status', 'Pending'),
                        data.get('remarks', '')
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO milestones
                        (assignment_id, milestone_no, title, description, target_date, tentative_date,
                         tentative_date_status, revenue_percent,
                         invoice_raised, invoice_raised_date, payment_received, payment_received_date,
                         status, remarks)
                        VALUES (?, ?, ?, ?, ?, ?, 'APPROVED', ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        assignment_id,
                        next_no,
                        title,
                        data.get('description', ''),
                        target_date,
                        target_date,  # tentative_date defaults to target_date
                        float(data.get('revenue_percent', 0) or 0),
                        invoice_raised,
                        data.get('invoice_raised_date') or None,
                        payment_received,
                        data.get('payment_received_date') or None,
                        data.get('status', 'Pending'),
                        data.get('remarks', '')
                    ))

        # Delete milestones that were removed
        ids_to_delete = existing_ids - processed_ids
        for mid in ids_to_delete:
            if USE_POSTGRES:
                cursor.execute("DELETE FROM milestones WHERE id = %s", (mid,))
            else:
                cursor.execute("DELETE FROM milestones WHERE id = ?", (mid,))

        # Recalculate assignment progress
        if USE_POSTGRES:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN payment_received = 1 THEN revenue_percent ELSE 0 END), 0) as paid_pct,
                    COALESCE(SUM(CASE WHEN invoice_raised = 1 AND payment_received = 0 THEN revenue_percent * 0.8 ELSE 0 END), 0) as pending_pct
                FROM milestones WHERE assignment_id = %s
            """, (assignment_id,))
        else:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN payment_received = 1 THEN revenue_percent ELSE 0 END), 0) as paid_pct,
                    COALESCE(SUM(CASE WHEN invoice_raised = 1 AND payment_received = 0 THEN revenue_percent * 0.8 ELSE 0 END), 0) as pending_pct
                FROM milestones WHERE assignment_id = ?
            """, (assignment_id,))
        progress = cursor.fetchone()
        physical_progress = (progress['paid_pct'] or 0) + (progress['pending_pct'] or 0)

        # Calculate timeline progress
        if USE_POSTGRES:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'Delayed' THEN 1 ELSE 0 END) as delayed
                FROM milestones WHERE assignment_id = %s
            """, (assignment_id,))
        else:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'Delayed' THEN 1 ELSE 0 END) as delayed
                FROM milestones WHERE assignment_id = ?
            """, (assignment_id,))
        timeline = cursor.fetchone()
        if timeline['total'] > 0:
            timeline_progress = ((timeline['completed'] or 0) / timeline['total']) * 100
            # Reduce by delay percentage
            if timeline['delayed']:
                timeline_progress = max(0, timeline_progress - (timeline['delayed'] / timeline['total']) * 20)
        else:
            timeline_progress = 0

        # Calculate invoice and payment amounts
        total_value = assignment.get('total_value') or assignment.get('gross_value') or 0
        if USE_POSTGRES:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN invoice_raised = 1 THEN revenue_percent ELSE 0 END), 0) as invoiced_pct,
                    COALESCE(SUM(CASE WHEN payment_received = 1 THEN revenue_percent ELSE 0 END), 0) as paid_pct
                FROM milestones WHERE assignment_id = %s
            """, (assignment_id,))
        else:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN invoice_raised = 1 THEN revenue_percent ELSE 0 END), 0) as invoiced_pct,
                    COALESCE(SUM(CASE WHEN payment_received = 1 THEN revenue_percent ELSE 0 END), 0) as paid_pct
                FROM milestones WHERE assignment_id = ?
            """, (assignment_id,))
        amounts = cursor.fetchone()
        invoice_amount = total_value * (amounts['invoiced_pct'] or 0) / 100
        amount_received = total_value * (amounts['paid_pct'] or 0) / 100

        # Calculate shareable revenue
        total_revenue = amount_received + (invoice_amount - amount_received) * 0.8

        # Reset milestone approval if previously approved (re-approval needed on edit)
        ms_reset = ""
        if assignment.get('milestone_approval_status') == 'APPROVED':
            ms_reset = ", milestone_approval_status = 'SUBMITTED'"

        cursor.execute(f"""
            UPDATE assignments SET
                physical_progress_percent = ?,
                timeline_progress_percent = ?,
                invoice_amount = ?,
                amount_received = ?,
                total_revenue = ?
                {ms_reset},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (physical_progress, timeline_progress, invoice_amount, amount_received, total_revenue, assignment_id))

    # Check if user wants to continue to next step in wizard
    next_step = form_data.get('next_step', '')
    if next_step == 'cost_estimate':
        return RedirectResponse(url=f"/assignment/expenditure/{assignment_id}?wizard=1", status_code=302)

    return RedirectResponse(url=f"/assignment/view/{assignment_id}", status_code=302)


@router.post("/milestones/{assignment_id}/request-tentative-change")
async def request_tentative_date_change(request: Request, assignment_id: int):
    """Request a tentative date change (by Team Leader, requires Head approval)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    form_data = await request.form()
    milestone_id = form_data.get('milestone_id')
    new_tentative_date = form_data.get('new_tentative_date')
    reason = form_data.get('reason', '').strip()

    if not milestone_id or not new_tentative_date:
        return RedirectResponse(url=f"/assignment/milestones/{assignment_id}", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Update milestone with pending tentative date change
        cursor.execute("""
            UPDATE milestones SET
                tentative_date = ?,
                tentative_date_status = 'PENDING',
                tentative_date_reason = ?,
                tentative_date_requested_by = ?,
                tentative_date_requested_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND assignment_id = ?
        """, (new_tentative_date, reason, user['officer_id'], milestone_id, assignment_id))

        # Log the request
        cursor.execute("""
            INSERT INTO approval_history (action_by, action_type, assignment_id, details)
            VALUES (?, 'TENTATIVE_DATE_REQUEST', ?, ?)
        """, (user['officer_id'], assignment_id, f"milestone_id={milestone_id}, new_date={new_tentative_date}, reason={reason}"))

    return RedirectResponse(url=f"/assignment/milestones/{assignment_id}", status_code=302)


@router.get("/select-activity-type", response_class=HTMLResponse)
async def select_activity_type_page(request: Request):
    """Display activity type selection page."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "new_activity_type.html",
        {
            "request": request,
            "user": user
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_assignment_page(request: Request):
    """Display new assignment creation form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Get activity type from query parameter
    activity_type = request.query_params.get('type', 'ASSIGNMENT')
    if activity_type not in ['ASSIGNMENT', 'DEVELOPMENT']:
        activity_type = 'ASSIGNMENT'

    officers = get_officers_list()
    offices = get_offices_list()

    return templates.TemplateResponse(
        "new_assignment_form.html",
        {
            "request": request,
            "user": user,
            "officers": officers,
            "offices": offices,
            "activity_type": activity_type,
            "status_options": get_config_options('status'),
            "client_type_options": get_config_options('client_type'),
            "domain_options": get_config_options('domain')
        }
    )


@router.post("/new")
async def create_assignment(request: Request):
    """Create a new assignment."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form_data = await request.form()

    assignment_type = form_data.get('type', 'ASSIGNMENT')
    office_id = form_data.get('office_id')
    title = form_data.get('title', '').strip()

    # Handle Development Work - notional value from man_days
    man_days = float(form_data.get('man_days', 0) or 0)
    daily_rate = 0.20  # 20k per day = 0.20 Lakhs

    if assignment_type == 'DEVELOPMENT':
        # For Development Work, calculate notional value from man-days
        total_value = man_days * daily_rate
        is_notional = 1
    else:
        total_value = float(form_data.get('total_value', 0) or 0)
        is_notional = 0

    if not title or not office_id:
        return RedirectResponse(url=f"/assignment/new?type={assignment_type}", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Generate assignment number
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_no FROM assignments
                WHERE office_id = %s AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM CURRENT_DATE)
            """, (office_id,))
        else:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_no FROM assignments
                WHERE office_id = ? AND strftime('%Y', created_at) = strftime('%Y', 'now')
            """, (office_id,))
        next_no = cursor.fetchone()['next_no']

        import datetime
        year = datetime.datetime.now().year
        assignment_no = f"{office_id}/{year}/{next_no:03d}"

        # Insert assignment
        cursor.execute("""
            INSERT INTO assignments
            (assignment_no, type, title, office_id, status, total_value, gross_value,
             client, client_type, city, domain, sub_domain, work_order_date, start_date, target_date,
             team_leader_officer_id, tor_scope, man_days, daily_rate, is_notional)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            assignment_no,
            assignment_type,
            title,
            office_id,
            form_data.get('status', 'Pipeline'),
            total_value,
            total_value,
            form_data.get('client', ''),
            form_data.get('client_type', ''),
            form_data.get('city', ''),
            form_data.get('domain', ''),
            form_data.get('sub_domain', ''),
            form_data.get('work_order_date') or None,
            form_data.get('start_date') or None,
            form_data.get('target_date') or None,
            form_data.get('team_leader_officer_id') or None,
            form_data.get('tor_scope', ''),
            man_days,
            daily_rate,
            is_notional
        ))

        assignment_id = cursor.lastrowid

        # Process milestones from form
        milestone_data = {}
        for key, value in form_data.items():
            if key.startswith('milestone_'):
                parts = key.split('_')
                if len(parts) >= 3:
                    idx = parts[1]
                    field = '_'.join(parts[2:])
                    if idx not in milestone_data:
                        milestone_data[idx] = {}
                    milestone_data[idx][field] = value

        milestone_no = 1
        for idx in sorted(milestone_data.keys()):
            data = milestone_data[idx]
            title = data.get('title', '').strip()
            if title:
                cursor.execute("""
                    INSERT INTO milestones
                    (assignment_id, milestone_no, title, description, target_date, revenue_percent, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    assignment_id,
                    milestone_no,
                    title,
                    data.get('description', ''),
                    data.get('target_date') or None,
                    float(data.get('revenue_percent', 0) or 0),
                    'Pending'
                ))
                milestone_no += 1

    # Redirect to milestones form to start the wizard flow
    return RedirectResponse(url=f"/assignment/milestones/{assignment_id}?wizard=1", status_code=302)


@router.get("/expenditure/{assignment_id}", response_class=HTMLResponse)
async def manage_expenditure(request: Request, assignment_id: int):
    """Display expenditure management page."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get expenditure heads grouped by category
        cursor.execute("""
            SELECT * FROM expenditure_heads ORDER BY category, head_code
        """)
        expenditure_heads = [dict(row) for row in cursor.fetchall()]

        # Get existing expenditure items for this assignment
        cursor.execute("""
            SELECT ei.*, eh.head_code, eh.head_name, eh.category
            FROM expenditure_items ei
            JOIN expenditure_heads eh ON ei.head_id = eh.id
            WHERE ei.assignment_id = ?
            ORDER BY eh.category, eh.head_code
        """, (assignment_id,))
        expenditure_items = [dict(row) for row in cursor.fetchall()]

        # Create a lookup for existing items by head_id
        existing_by_head = {item['head_id']: item for item in expenditure_items}

    return templates.TemplateResponse(
        "expenditure_form.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "expenditure_heads": expenditure_heads,
            "existing_by_head": existing_by_head
        }
    )


@router.post("/expenditure/{assignment_id}")
async def save_expenditure(request: Request, assignment_id: int):
    """Save expenditure updates."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    form_data = await request.form()

    with get_db() as conn:
        cursor = conn.cursor()

        total_estimated = 0
        total_actual = 0

        # Process form data for each expenditure head
        for key, value in form_data.items():
            if key.startswith('estimated_'):
                head_id = int(key.replace('estimated_', ''))
                estimated = float(value) if value else 0
                actual_key = f'actual_{head_id}'
                remarks_key = f'remarks_{head_id}'
                actual = float(form_data.get(actual_key, 0) or 0)
                remarks = form_data.get(remarks_key, '')

                total_estimated += estimated
                total_actual += actual

                if estimated > 0 or actual > 0:
                    # Check if entry exists
                    cursor.execute("""
                        SELECT id FROM expenditure_items
                        WHERE assignment_id = ? AND head_id = ?
                    """, (assignment_id, head_id))
                    existing = cursor.fetchone()

                    if existing:
                        cursor.execute("""
                            UPDATE expenditure_items SET
                                estimated_amount = ?,
                                actual_amount = ?,
                                remarks = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE assignment_id = ? AND head_id = ?
                        """, (estimated, actual, remarks, assignment_id, head_id))
                    else:
                        cursor.execute("""
                            INSERT INTO expenditure_items
                            (assignment_id, head_id, estimated_amount, actual_amount, remarks)
                            VALUES (?, ?, ?, ?, ?)
                        """, (assignment_id, head_id, estimated, actual, remarks))
                else:
                    # Remove if both are zero
                    cursor.execute("""
                        DELETE FROM expenditure_items
                        WHERE assignment_id = ? AND head_id = ?
                    """, (assignment_id, head_id))

        # Update assignment total expenditure and reset cost approval if previously approved
        cost_reset = ""
        if assignment.get('cost_approval_status') == 'APPROVED':
            cost_reset = ", cost_approval_status = 'SUBMITTED'"

        cursor.execute(f"""
            UPDATE assignments SET
                total_expenditure = ?,
                surplus_deficit = COALESCE(total_revenue, 0) - ?
                {cost_reset},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (total_actual, total_actual, assignment_id))

    # Check if user wants to continue to next step in wizard
    next_step = form_data.get('next_step', '')
    if next_step == 'team_revenue':
        return RedirectResponse(url=f"/revenue/edit/{assignment_id}?wizard=1", status_code=302)

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?tab=cost", status_code=302)


def _get_fy_for_date(d):
    """Return FY string like '2024-25' for a given date."""
    if isinstance(d, str):
        from datetime import datetime
        d = datetime.strptime(d, '%Y-%m-%d').date()
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    else:
        return f"{d.year - 1}-{str(d.year)[2:]}"


@router.get("/expenditure-entry/{assignment_id}", response_class=HTMLResponse)
async def expenditure_entry_form(request: Request, assignment_id: int):
    """Display form to add a date-wise expenditure entry."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM expenditure_heads ORDER BY category, head_code")
        expenditure_heads = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "expenditure_entry_form.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "expenditure_heads": expenditure_heads
        }
    )


@router.post("/expenditure-entry/{assignment_id}")
async def save_expenditure_entry(request: Request, assignment_id: int):
    """Save a date-wise expenditure entry and update parent totals."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    form_data = await request.form()
    head_id = int(form_data.get('head_id', 0))
    entry_date = form_data.get('entry_date', '')
    amount = float(form_data.get('amount', 0) or 0)
    description = form_data.get('description', '').strip()
    voucher_reference = form_data.get('voucher_reference', '').strip()

    if not head_id or not entry_date or amount <= 0:
        return RedirectResponse(url=f"/assignment/expenditure-entry/{assignment_id}", status_code=302)

    # Calculate FY period from entry_date
    fy_period = _get_fy_for_date(entry_date)

    PH = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        # Find or create the parent expenditure_item
        cursor.execute(f"""
            SELECT id FROM expenditure_items
            WHERE assignment_id = {PH} AND head_id = {PH}
        """, (assignment_id, head_id))
        parent = cursor.fetchone()

        if parent:
            expenditure_item_id = parent['id']
        else:
            cursor.execute(f"""
                INSERT INTO expenditure_items (assignment_id, head_id, estimated_amount, actual_amount)
                VALUES ({PH}, {PH}, 0, 0)
            """, (assignment_id, head_id))
            if USE_POSTGRES:
                cursor.execute("SELECT lastval()")
                expenditure_item_id = cursor.fetchone()[0]
            else:
                expenditure_item_id = cursor.lastrowid

        # Insert the entry
        cursor.execute(f"""
            INSERT INTO expenditure_entries
            (expenditure_item_id, assignment_id, head_id, entry_date, amount, fy_period, description, voucher_reference, entered_by)
            VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        """, (expenditure_item_id, assignment_id, head_id, entry_date, amount, fy_period, description, voucher_reference, user['officer_id']))

        # Update parent expenditure_item actual_amount = SUM of child entries
        cursor.execute(f"""
            UPDATE expenditure_items SET
                actual_amount = (
                    SELECT COALESCE(SUM(amount), 0) FROM expenditure_entries
                    WHERE expenditure_item_id = {PH}
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {PH}
        """, (expenditure_item_id, expenditure_item_id))

        # Update assignment total_expenditure = SUM of all expenditure_items actual_amount
        cursor.execute(f"""
            UPDATE assignments SET
                total_expenditure = (
                    SELECT COALESCE(SUM(actual_amount), 0) FROM expenditure_items
                    WHERE assignment_id = {PH}
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {PH}
        """, (assignment_id, assignment_id))

        # Recalculate surplus_deficit
        cursor.execute(f"""
            UPDATE assignments SET
                surplus_deficit = COALESCE(total_revenue, 0) - COALESCE(total_expenditure, 0)
            WHERE id = {PH}
        """, (assignment_id,))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?tab=cost", status_code=302)
