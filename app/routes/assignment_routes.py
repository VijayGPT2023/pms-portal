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
        cursor.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


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

    template_name = "assignment_form.html" if assignment['type'] == 'ASSIGNMENT' else "training_form.html"

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
    faculty2_officer_id: Optional[str] = Form(None)
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

        if assignment['type'] == 'ASSIGNMENT':
            cursor.execute("""
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
                    details_filled = 1,
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
        else:  # TRAINING
            cursor.execute("""
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
                    details_filled = 1,
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
    """View assignment details (read-only)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    # Get related officer names
    officers = {}
    with get_db() as conn:
        cursor = conn.cursor()
        for field in ['team_leader_officer_id', 'faculty1_officer_id', 'faculty2_officer_id']:
            if assignment.get(field):
                cursor.execute("SELECT name FROM officers WHERE officer_id = ?", (assignment[field],))
                row = cursor.fetchone()
                if row:
                    officers[field] = row['name']

        # Get revenue shares for this assignment
        cursor.execute("""
            SELECT rs.*, o.name as officer_name
            FROM revenue_shares rs
            JOIN officers o ON rs.officer_id = o.officer_id
            WHERE rs.assignment_id = ?
            ORDER BY rs.share_percent DESC
        """, (assignment_id,))
        revenue_shares = [dict(row) for row in cursor.fetchall()]

        # Get milestones for this assignment
        cursor.execute("""
            SELECT * FROM milestones
            WHERE assignment_id = ?
            ORDER BY milestone_no
        """, (assignment_id,))
        milestones = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "assignment_view.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "officers": officers,
            "revenue_shares": revenue_shares,
            "milestones": milestones
        }
    )


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
                cursor.execute("SELECT COALESCE(MAX(milestone_no), 0) + 1 FROM milestones WHERE assignment_id = ?",
                             (assignment_id,))
                next_no = cursor.fetchone()[0]

                cursor.execute("""
                    INSERT INTO milestones
                    (assignment_id, milestone_no, title, description, target_date, revenue_percent,
                     invoice_raised, invoice_raised_date, payment_received, payment_received_date,
                     status, remarks)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    assignment_id,
                    next_no,
                    title,
                    data.get('description', ''),
                    data.get('target_date') or None,
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
            cursor.execute("DELETE FROM milestones WHERE id = ?", (mid,))

        # Recalculate assignment progress
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN payment_received = 1 THEN revenue_percent ELSE 0 END), 0) as paid_pct,
                COALESCE(SUM(CASE WHEN invoice_raised = 1 AND payment_received = 0 THEN revenue_percent * 0.8 ELSE 0 END), 0) as pending_pct
            FROM milestones WHERE assignment_id = ?
        """, (assignment_id,))
        progress = cursor.fetchone()
        physical_progress = (progress['paid_pct'] or 0) + (progress['pending_pct'] or 0)

        # Calculate timeline progress
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

        cursor.execute("""
            UPDATE assignments SET
                physical_progress_percent = ?,
                timeline_progress_percent = ?,
                invoice_amount = ?,
                amount_received = ?,
                total_revenue = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (physical_progress, timeline_progress, invoice_amount, amount_received, total_revenue, assignment_id))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}", status_code=302)


@router.get("/new", response_class=HTMLResponse)
async def new_assignment_page(request: Request):
    """Display new assignment creation form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    officers = get_officers_list()
    offices = get_offices_list()

    return templates.TemplateResponse(
        "new_assignment_form.html",
        {
            "request": request,
            "user": user,
            "officers": officers,
            "offices": offices,
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
    total_value = float(form_data.get('total_value', 0) or 0)

    if not title or not office_id:
        return RedirectResponse(url="/assignment/new", status_code=302)

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
             team_leader_officer_id, tor_scope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            form_data.get('tor_scope', '')
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

    return RedirectResponse(url=f"/assignment/view/{assignment_id}", status_code=302)


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

        # Update assignment total expenditure
        cursor.execute("""
            UPDATE assignments SET
                total_expenditure = ?,
                surplus_deficit = COALESCE(total_revenue, 0) - ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (total_actual, total_actual, assignment_id))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}", status_code=302)
