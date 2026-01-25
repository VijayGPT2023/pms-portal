"""
Routes for Enquiry Management (Stage 1 of 4-stage workflow).
Workflow: Any officer creates → Head approves/allocates → Officer works → Convert to PR

Enquiry → Proposal Request → Proposal → Work Order
"""
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import date

from app.database import (
    get_db, generate_enquiry_number, generate_pr_number,
    get_pre_revenue_metrics
)
from app.dependencies import get_current_user
from app.config import TEMPLATES_DIR

router = APIRouter(prefix="/enquiry", tags=["enquiry"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def is_office_head(user, office_id):
    """Check if user is Head of the given office."""
    admin_role = user.get('admin_role_id', '')
    if admin_role in ['ADMIN', 'DG', 'DDG']:
        return True

    # Check if user is head of this office
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM officer_roles
            WHERE officer_id = ?
            AND role_type IN ('DG', 'DDG-I', 'DDG-II', 'RD_HEAD', 'GROUP_HEAD')
            AND (effective_to IS NULL OR effective_to >= DATE('now'))
        """, (user['officer_id'],))
        if cursor.fetchone():
            return True

        # Check if user's office matches and they have head role
        if user.get('office_id') == office_id:
            cursor.execute("""
                SELECT 1 FROM officer_roles
                WHERE officer_id = ?
                AND role_type IN ('RD_HEAD', 'GROUP_HEAD', 'TEAM_LEADER')
                AND (effective_to IS NULL OR effective_to >= DATE('now'))
            """, (user['officer_id'],))
            if cursor.fetchone():
                return True

    return admin_role == 'HEAD'


def can_edit_enquiry(user, enquiry):
    """Check if user can edit this enquiry."""
    # Creator can edit if pending approval
    if enquiry.get('created_by') == user['officer_id'] and enquiry.get('approval_status') == 'PENDING':
        return True
    # Allocated officer can update progress
    if enquiry.get('officer_id') == user['officer_id']:
        return True
    # Head can always edit
    if is_office_head(user, enquiry.get('office_id')):
        return True
    return False


@router.get("/", response_class=HTMLResponse)
async def list_enquiries(request: Request, status: str = None, office: str = None, view: str = None):
    """List all enquiries with filters."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["1=1"]
        params = []

        if status:
            conditions.append("e.status = ?")
            params.append(status)

        if office:
            conditions.append("e.office_id = ?")
            params.append(office)

        # View filters
        admin_role = user.get('admin_role_id', '')
        if view == 'pending_approval' and admin_role in ['ADMIN', 'DG', 'DDG', 'HEAD']:
            conditions.append("e.approval_status = 'PENDING'")
        elif view == 'my_created':
            conditions.append("e.created_by = ?")
            params.append(user['officer_id'])
        elif view == 'my_allocated':
            conditions.append("e.officer_id = ?")
            params.append(user['officer_id'])
        elif admin_role not in ['ADMIN', 'DG', 'DDG']:
            # Regular users see their office's enquiries
            conditions.append("e.office_id = ?")
            params.append(user['office_id'])

        where_clause = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT e.*, o.name as officer_name, off.office_name,
                   creator.name as created_by_name, approver.name as approved_by_name
            FROM enquiries e
            LEFT JOIN officers o ON e.officer_id = o.officer_id
            LEFT JOIN offices off ON e.office_id = off.office_id
            LEFT JOIN officers creator ON e.created_by = creator.officer_id
            LEFT JOIN officers approver ON e.approved_by = approver.officer_id
            WHERE {where_clause}
            ORDER BY e.created_at DESC
        """, params)
        enquiries = [dict(row) for row in cursor.fetchall()]

        # Get offices for filter dropdown
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        # Get status counts
        cursor.execute("""
            SELECT status, COUNT(*) as count FROM enquiries
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Pending approval count for heads
        cursor.execute("SELECT COUNT(*) as count FROM enquiries WHERE approval_status = 'PENDING'")
        pending_approval_count = cursor.fetchone()['count']

    # Check if user is a head (can approve)
    is_head = is_office_head(user, user.get('office_id'))

    return templates.TemplateResponse("enquiry_list.html", {
        "request": request,
        "user": user,
        "enquiries": enquiries,
        "offices": offices,
        "status_counts": status_counts,
        "pending_approval_count": pending_approval_count,
        "filter_status": status,
        "filter_office": office,
        "filter_view": view,
        "is_head": is_head
    })


@router.get("/new", response_class=HTMLResponse)
async def new_enquiry_form(request: Request):
    """Display form to create new enquiry - accessible by any logged-in officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get officers for assignment (Heads will allocate later)
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers WHERE is_active = 1
            ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

        # Get offices
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        # Get domains from config
        cursor.execute("""
            SELECT option_value, option_label FROM config_options
            WHERE category = 'domain' AND is_active = 1
            ORDER BY sort_order
        """)
        domains = [dict(row) for row in cursor.fetchall()]

        # Get client types
        cursor.execute("""
            SELECT option_value, option_label FROM config_options
            WHERE category = 'client_type' AND is_active = 1
            ORDER BY sort_order
        """)
        client_types = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("enquiry_form.html", {
        "request": request,
        "user": user,
        "officers": officers,
        "offices": offices,
        "domains": domains,
        "client_types": client_types,
        "enquiry": None,
        "mode": "new",
        "is_head": is_office_head(user, user.get('office_id'))
    })


@router.post("/create")
async def create_enquiry(
    request: Request,
    client_name: str = Form(...),
    client_type: str = Form(None),
    domain: str = Form(None),
    sub_domain: str = Form(None),
    office_id: str = Form(...),
    officer_id: str = Form(None),
    description: str = Form(None),
    estimated_value: float = Form(None),
    target_date: str = Form(None),
    remarks: str = Form(None)
):
    """Create a new enquiry - any officer can create, pending Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    enquiry_number = generate_enquiry_number(office_id)

    # If creator is a Head, auto-approve
    is_head = is_office_head(user, office_id)
    initial_status = 'APPROVED' if is_head else 'PENDING_APPROVAL'
    approval_status = 'APPROVED' if is_head else 'PENDING'

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO enquiries
            (enquiry_number, client_name, client_type, domain, sub_domain,
             office_id, officer_id, description, estimated_value, target_date,
             remarks, status, approval_status, approved_by, approved_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (enquiry_number, client_name, client_type, domain, sub_domain,
              office_id, officer_id if is_head else None, description, estimated_value, target_date,
              remarks, initial_status, approval_status,
              user['officer_id'] if is_head else None,
              'CURRENT_TIMESTAMP' if is_head else None,
              user['officer_id']))

        enquiry_id = cursor.lastrowid

        # Log activity
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CREATE', 'enquiry', ?, ?)
        """, (user['officer_id'], enquiry_id, f"Created enquiry {enquiry_number}"))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.get("/{enquiry_id}", response_class=HTMLResponse)
async def view_enquiry(request: Request, enquiry_id: int):
    """View enquiry details."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT e.*, o.name as officer_name, off.office_name,
                   creator.name as created_by_name, approver.name as approved_by_name
            FROM enquiries e
            LEFT JOIN officers o ON e.officer_id = o.officer_id
            LEFT JOIN offices off ON e.office_id = off.office_id
            LEFT JOIN officers creator ON e.created_by = creator.officer_id
            LEFT JOIN officers approver ON e.approved_by = approver.officer_id
            WHERE e.id = ?
        """, (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        enquiry = dict(enquiry)

        # Check if converted to PR
        cursor.execute("""
            SELECT * FROM proposal_requests WHERE enquiry_id = ?
        """, (enquiry_id,))
        linked_pr = cursor.fetchone()
        if linked_pr:
            enquiry['linked_pr'] = dict(linked_pr)

        # Get activity log
        cursor.execute("""
            SELECT al.*, o.name as actor_name
            FROM activity_log al
            LEFT JOIN officers o ON al.actor_id = o.officer_id
            WHERE al.entity_type = 'enquiry' AND al.entity_id = ?
            ORDER BY al.created_at DESC
        """, (enquiry_id,))
        activities = [dict(row) for row in cursor.fetchall()]

        # Get officers for allocation dropdown (if head)
        cursor.execute("""
            SELECT officer_id, name, office_id FROM officers
            WHERE is_active = 1 ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

    # Check permissions
    can_edit = can_edit_enquiry(user, enquiry)
    is_head = is_office_head(user, enquiry.get('office_id'))
    is_allocated_officer = enquiry.get('officer_id') == user['officer_id']
    is_creator = enquiry.get('created_by') == user['officer_id']

    return templates.TemplateResponse("enquiry_view.html", {
        "request": request,
        "user": user,
        "enquiry": enquiry,
        "activities": activities,
        "officers": officers,
        "can_edit": can_edit,
        "is_head": is_head,
        "is_allocated_officer": is_allocated_officer,
        "is_creator": is_creator
    })


@router.get("/{enquiry_id}/edit", response_class=HTMLResponse)
async def edit_enquiry_form(request: Request, enquiry_id: int):
    """Display form to edit enquiry."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        enquiry = dict(enquiry)

        if not can_edit_enquiry(user, enquiry):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        # Get dropdowns
        cursor.execute("SELECT officer_id, name, office_id FROM officers WHERE is_active = 1 ORDER BY name")
        officers = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT option_value, option_label FROM config_options WHERE category = 'domain' AND is_active = 1")
        domains = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT option_value, option_label FROM config_options WHERE category = 'client_type' AND is_active = 1")
        client_types = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("enquiry_form.html", {
        "request": request,
        "user": user,
        "enquiry": enquiry,
        "officers": officers,
        "offices": offices,
        "domains": domains,
        "client_types": client_types,
        "mode": "edit",
        "is_head": is_office_head(user, enquiry.get('office_id'))
    })


@router.post("/{enquiry_id}/update")
async def update_enquiry(
    request: Request,
    enquiry_id: int,
    client_name: str = Form(...),
    client_type: str = Form(None),
    domain: str = Form(None),
    sub_domain: str = Form(None),
    office_id: str = Form(...),
    officer_id: str = Form(None),
    description: str = Form(None),
    estimated_value: float = Form(None),
    target_date: str = Form(None),
    remarks: str = Form(None)
):
    """Update an existing enquiry."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()
        if not enquiry or not can_edit_enquiry(user, dict(enquiry)):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE enquiries SET
                client_name = ?, client_type = ?, domain = ?, sub_domain = ?,
                office_id = ?, officer_id = ?, description = ?, estimated_value = ?,
                target_date = ?, remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (client_name, client_type, domain, sub_domain, office_id, officer_id,
              description, estimated_value, target_date, remarks, enquiry_id))

        # Log activity
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'enquiry', ?, 'Updated enquiry details')
        """, (user['officer_id'], enquiry_id))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/approve")
async def approve_enquiry(request: Request, enquiry_id: int, officer_id: str = Form(...)):
    """Head approves enquiry and allocates to an officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        if not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE enquiries SET
                status = 'APPROVED', approval_status = 'APPROVED',
                officer_id = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (officer_id, user['officer_id'], enquiry_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'enquiry', ?, 'Approved and allocated to officer')
        """, (user['officer_id'], enquiry_id))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/reject")
async def reject_enquiry(request: Request, enquiry_id: int, rejection_reason: str = Form(...)):
    """Head rejects enquiry."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        if not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE enquiries SET
                status = 'REJECTED', approval_status = 'REJECTED',
                rejection_reason = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_reason, user['officer_id'], enquiry_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'enquiry', ?, ?)
        """, (user['officer_id'], enquiry_id, f"Rejected: {rejection_reason}"))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/reallocate")
async def reallocate_enquiry(request: Request, enquiry_id: int, officer_id: str = Form(...)):
    """Head reallocates enquiry to a different officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        if not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        old_officer = enquiry['officer_id']
        cursor.execute("""
            UPDATE enquiries SET officer_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (officer_id, enquiry_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REALLOCATE', 'enquiry', ?, ?)
        """, (user['officer_id'], enquiry_id, f"Reallocated from {old_officer} to {officer_id}"))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/update-progress")
async def update_progress(request: Request, enquiry_id: int, current_update: str = Form(...), status: str = Form(None)):
    """Allocated officer updates progress on the enquiry."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        # Only allocated officer or head can update progress
        if enquiry['officer_id'] != user['officer_id'] and not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        new_status = status if status else enquiry['status']
        if new_status == 'APPROVED':
            new_status = 'IN_PROGRESS'  # Move to in-progress once work starts

        cursor.execute("""
            UPDATE enquiries SET
                current_update = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (current_update, new_status, enquiry_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'enquiry', ?, ?)
        """, (user['officer_id'], enquiry_id, f"Progress update: {current_update[:100]}"))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/convert-to-pr")
async def convert_to_pr(request: Request, enquiry_id: int):
    """Convert enquiry to Proposal Request (Stage 1 → Stage 2)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        # Only allocated officer or head can convert
        if enquiry['officer_id'] != user['officer_id'] and not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        if enquiry['status'] == 'CONVERTED_TO_PR':
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=already_converted", status_code=302)

        pr_number = generate_pr_number(enquiry['office_id'])

        cursor.execute("""
            INSERT INTO proposal_requests
            (pr_number, enquiry_id, client_name, client_type, domain, sub_domain,
             office_id, officer_id, description, estimated_value,
             status, approval_status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', 'PENDING', ?)
        """, (pr_number, enquiry_id, enquiry['client_name'], enquiry['client_type'],
              enquiry['domain'], enquiry['sub_domain'], enquiry['office_id'],
              enquiry['officer_id'], enquiry['description'], enquiry['estimated_value'],
              user['officer_id']))

        pr_id = cursor.lastrowid

        cursor.execute("""
            UPDATE enquiries SET status = 'CONVERTED_TO_PR', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (enquiry_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CONVERT', 'enquiry', ?, ?)
        """, (user['officer_id'], enquiry_id, f"Converted to PR: {pr_number}"))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{enquiry_id}/drop")
async def drop_enquiry(request: Request, enquiry_id: int, drop_reason: str = Form(...)):
    """Mark enquiry as dropped."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        # Only head can drop
        if not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE enquiries SET
                status = 'DROPPED', drop_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (drop_reason, enquiry_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'DROP', 'enquiry', ?, ?)
        """, (user['officer_id'], enquiry_id, f"Dropped: {drop_reason}"))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/hold")
async def hold_enquiry(request: Request, enquiry_id: int):
    """Put enquiry on hold."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        if enquiry['officer_id'] != user['officer_id'] and not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE enquiries SET status = 'ON_HOLD', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (enquiry_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'enquiry', ?, 'Put on hold')
        """, (user['officer_id'], enquiry_id))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.post("/{enquiry_id}/resume")
async def resume_enquiry(request: Request, enquiry_id: int):
    """Resume enquiry from hold."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,))
        enquiry = cursor.fetchone()

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        if enquiry['officer_id'] != user['officer_id'] and not is_office_head(user, enquiry['office_id']):
            return RedirectResponse(url=f"/enquiry/{enquiry_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE enquiries SET status = 'IN_PROGRESS', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (enquiry_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'enquiry', ?, 'Resumed from hold')
        """, (user['officer_id'], enquiry_id))

    return RedirectResponse(url=f"/enquiry/{enquiry_id}", status_code=302)


@router.get("/metrics/pre-revenue", response_class=HTMLResponse)
async def pre_revenue_metrics_page(request: Request, fy: str = None, office: str = None):
    """Display pre-revenue activity metrics (Enquiry → Proposal stages)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.database import get_current_fy

    fy_period = fy or get_current_fy()

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

    metrics = get_pre_revenue_metrics(office_id=office, fy_period=fy_period)

    return templates.TemplateResponse("pre_revenue_metrics.html", {
        "request": request,
        "user": user,
        "metrics": metrics,
        "offices": offices,
        "filter_fy": fy_period,
        "filter_office": office
    })
