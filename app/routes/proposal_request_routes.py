"""
Routes for Proposal Request Management (Stage 2 of 4-stage workflow).
Workflow: Any officer creates → Head approves/allocates → Officer works → Convert to Proposal

Enquiry → Proposal Request → Proposal → Work Order
"""
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db, generate_proposal_number
from app.dependencies import get_current_user
from app.config import TEMPLATES_DIR

router = APIRouter(prefix="/proposal-request", tags=["proposal-request"])
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


def can_edit_pr(user, pr):
    """Check if user can edit this proposal request."""
    # Creator can edit if pending approval
    if pr.get('created_by') == user['officer_id'] and pr.get('approval_status') == 'PENDING':
        return True
    # Allocated officer can update progress
    if pr.get('officer_id') == user['officer_id']:
        return True
    # Head can always edit
    if is_office_head(user, pr.get('office_id')):
        return True
    return False


@router.get("/", response_class=HTMLResponse)
async def list_proposal_requests(request: Request, status: str = None, office: str = None, view: str = None):
    """List all proposal requests with filters."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["1=1"]
        params = []

        if status:
            conditions.append("pr.status = ?")
            params.append(status)

        if office:
            conditions.append("pr.office_id = ?")
            params.append(office)

        # View filters
        admin_role = user.get('admin_role_id', '')
        if view == 'pending_approval' and admin_role in ['ADMIN', 'DG', 'DDG', 'HEAD']:
            conditions.append("pr.approval_status = 'PENDING'")
        elif view == 'my_created':
            conditions.append("pr.created_by = ?")
            params.append(user['officer_id'])
        elif view == 'my_allocated':
            conditions.append("pr.officer_id = ?")
            params.append(user['officer_id'])
        elif admin_role not in ['ADMIN', 'DG', 'DDG']:
            # Regular users see their office's PRs
            conditions.append("pr.office_id = ?")
            params.append(user['office_id'])

        where_clause = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT pr.*, o.name as officer_name, off.office_name,
                   e.enquiry_number, creator.name as created_by_name,
                   approver.name as approved_by_name
            FROM proposal_requests pr
            LEFT JOIN officers o ON pr.officer_id = o.officer_id
            LEFT JOIN offices off ON pr.office_id = off.office_id
            LEFT JOIN enquiries e ON pr.enquiry_id = e.id
            LEFT JOIN officers creator ON pr.created_by = creator.officer_id
            LEFT JOIN officers approver ON pr.approved_by = approver.officer_id
            WHERE {where_clause}
            ORDER BY pr.created_at DESC
        """, params)
        prs = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT status, COUNT(*) as count FROM proposal_requests
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Pending approval count for heads
        cursor.execute("SELECT COUNT(*) as count FROM proposal_requests WHERE approval_status = 'PENDING'")
        pending_approval_count = cursor.fetchone()['count']

    # Check if user is a head (can approve)
    is_head = is_office_head(user, user.get('office_id'))

    return templates.TemplateResponse("proposal_request_list.html", {
        "request": request,
        "user": user,
        "proposal_requests": prs,
        "offices": offices,
        "status_counts": status_counts,
        "pending_approval_count": pending_approval_count,
        "filter_status": status,
        "filter_office": office,
        "filter_view": view,
        "is_head": is_head
    })


@router.get("/new", response_class=HTMLResponse)
async def new_proposal_request_form(request: Request, from_enquiry: int = None):
    """Display form to create new proposal request - accessible by any logged-in officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    source_enquiry = None
    if from_enquiry:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM enquiries WHERE id = ?", (from_enquiry,))
            row = cursor.fetchone()
            if row:
                source_enquiry = dict(row)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers WHERE is_active = 1
            ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT option_value, option_label FROM config_options
            WHERE category = 'domain' AND is_active = 1
            ORDER BY sort_order
        """)
        domains = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT option_value, option_label FROM config_options
            WHERE category = 'client_type' AND is_active = 1
            ORDER BY sort_order
        """)
        client_types = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("proposal_request_form.html", {
        "request": request,
        "user": user,
        "officers": officers,
        "offices": offices,
        "domains": domains,
        "client_types": client_types,
        "pr": source_enquiry,  # Pre-fill from enquiry if available
        "mode": "new",
        "from_enquiry": from_enquiry,
        "is_head": is_office_head(user, user.get('office_id'))
    })


@router.post("/create")
async def create_proposal_request(
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
    remarks: str = Form(None),
    from_enquiry: int = Form(None)
):
    """Create a new proposal request - any officer can create, pending Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.database import generate_pr_number
    pr_number = generate_pr_number(office_id)

    # If creator is a Head, auto-approve
    is_head = is_office_head(user, office_id)
    initial_status = 'APPROVED' if is_head else 'PENDING_APPROVAL'
    approval_status = 'APPROVED' if is_head else 'PENDING'

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO proposal_requests
            (pr_number, enquiry_id, client_name, client_type, domain, sub_domain,
             office_id, officer_id, description, estimated_value, target_date,
             remarks, status, approval_status, approved_by, approved_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pr_number, from_enquiry, client_name, client_type, domain, sub_domain,
              office_id, officer_id if is_head else None, description, estimated_value, target_date,
              remarks, initial_status, approval_status,
              user['officer_id'] if is_head else None,
              'CURRENT_TIMESTAMP' if is_head else None,
              user['officer_id']))

        pr_id = cursor.lastrowid

        # If created from enquiry, update enquiry status
        if from_enquiry:
            cursor.execute("""
                UPDATE enquiries SET status = 'CONVERTED_TO_PR', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (from_enquiry,))

        # Log activity
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CREATE', 'proposal_request', ?, ?)
        """, (user['officer_id'], pr_id, f"Created proposal request {pr_number}"))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.get("/{pr_id}", response_class=HTMLResponse)
async def view_proposal_request(request: Request, pr_id: int):
    """View proposal request details."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT pr.*, o.name as officer_name, off.office_name,
                   e.enquiry_number, creator.name as created_by_name,
                   approver.name as approved_by_name
            FROM proposal_requests pr
            LEFT JOIN officers o ON pr.officer_id = o.officer_id
            LEFT JOIN offices off ON pr.office_id = off.office_id
            LEFT JOIN enquiries e ON pr.enquiry_id = e.id
            LEFT JOIN officers creator ON pr.created_by = creator.officer_id
            LEFT JOIN officers approver ON pr.approved_by = approver.officer_id
            WHERE pr.id = ?
        """, (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        pr = dict(pr)

        # Check if converted to Proposal
        cursor.execute("""
            SELECT * FROM proposals WHERE pr_id = ?
        """, (pr_id,))
        linked_proposal = cursor.fetchone()
        if linked_proposal:
            pr['linked_proposal'] = dict(linked_proposal)

        # Get source enquiry details
        if pr.get('enquiry_id'):
            cursor.execute("SELECT * FROM enquiries WHERE id = ?", (pr['enquiry_id'],))
            enquiry = cursor.fetchone()
            if enquiry:
                pr['enquiry'] = dict(enquiry)

        # Get activity log
        cursor.execute("""
            SELECT al.*, o.name as actor_name
            FROM activity_log al
            LEFT JOIN officers o ON al.actor_id = o.officer_id
            WHERE al.entity_type = 'proposal_request' AND al.entity_id = ?
            ORDER BY al.created_at DESC
        """, (pr_id,))
        activities = [dict(row) for row in cursor.fetchall()]

        # Get officers for allocation dropdown (if head)
        cursor.execute("""
            SELECT officer_id, name, office_id FROM officers
            WHERE is_active = 1 ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

    # Check permissions
    can_edit = can_edit_pr(user, pr)
    is_head = is_office_head(user, pr.get('office_id'))
    is_allocated_officer = pr.get('officer_id') == user['officer_id']
    is_creator = pr.get('created_by') == user['officer_id']

    return templates.TemplateResponse("proposal_request_view.html", {
        "request": request,
        "user": user,
        "pr": pr,
        "activities": activities,
        "officers": officers,
        "can_edit": can_edit,
        "is_head": is_head,
        "is_allocated_officer": is_allocated_officer,
        "is_creator": is_creator
    })


@router.get("/{pr_id}/edit", response_class=HTMLResponse)
async def edit_proposal_request_form(request: Request, pr_id: int):
    """Display form to edit proposal request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        pr = dict(pr)

        if not can_edit_pr(user, pr):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("SELECT officer_id, name, office_id FROM officers WHERE is_active = 1 ORDER BY name")
        officers = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT option_value, option_label FROM config_options WHERE category = 'domain' AND is_active = 1")
        domains = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT option_value, option_label FROM config_options WHERE category = 'client_type' AND is_active = 1")
        client_types = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("proposal_request_form.html", {
        "request": request,
        "user": user,
        "pr": pr,
        "officers": officers,
        "offices": offices,
        "domains": domains,
        "client_types": client_types,
        "mode": "edit",
        "is_head": is_office_head(user, pr.get('office_id'))
    })


@router.post("/{pr_id}/update")
async def update_proposal_request(
    request: Request,
    pr_id: int,
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
    """Update an existing proposal request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()
        if not pr or not can_edit_pr(user, dict(pr)):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposal_requests SET
                client_name = ?, client_type = ?, domain = ?, sub_domain = ?,
                office_id = ?, officer_id = ?, description = ?, estimated_value = ?,
                target_date = ?, remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (client_name, client_type, domain, sub_domain, office_id, officer_id,
              description, estimated_value, target_date, remarks, pr_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal_request', ?, 'Updated proposal request details')
        """, (user['officer_id'], pr_id))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/approve")
async def approve_proposal_request(request: Request, pr_id: int, officer_id: str = Form(...)):
    """Head approves proposal request and allocates to an officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        if not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposal_requests SET
                status = 'APPROVED', approval_status = 'APPROVED',
                officer_id = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (officer_id, user['officer_id'], pr_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'proposal_request', ?, 'Approved and allocated to officer')
        """, (user['officer_id'], pr_id))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/reject")
async def reject_proposal_request(request: Request, pr_id: int, rejection_reason: str = Form(...)):
    """Head rejects proposal request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        if not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposal_requests SET
                status = 'REJECTED', approval_status = 'REJECTED',
                rejection_reason = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_reason, user['officer_id'], pr_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'proposal_request', ?, ?)
        """, (user['officer_id'], pr_id, f"Rejected: {rejection_reason}"))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/reallocate")
async def reallocate_proposal_request(request: Request, pr_id: int, officer_id: str = Form(...)):
    """Head reallocates proposal request to a different officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        if not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        old_officer = pr['officer_id']
        cursor.execute("""
            UPDATE proposal_requests SET officer_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (officer_id, pr_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REALLOCATE', 'proposal_request', ?, ?)
        """, (user['officer_id'], pr_id, f"Reallocated from {old_officer} to {officer_id}"))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/update-progress")
async def update_progress(request: Request, pr_id: int, current_update: str = Form(...), status: str = Form(None)):
    """Allocated officer updates progress on the proposal request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        # Only allocated officer or head can update progress
        if pr['officer_id'] != user['officer_id'] and not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        new_status = status if status else pr['status']
        if new_status == 'APPROVED':
            new_status = 'IN_PROGRESS'  # Move to in-progress once work starts

        cursor.execute("""
            UPDATE proposal_requests SET
                current_update = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (current_update, new_status, pr_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal_request', ?, ?)
        """, (user['officer_id'], pr_id, f"Progress update: {current_update[:100]}"))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/convert-to-proposal")
async def convert_to_proposal(request: Request, pr_id: int):
    """Convert Proposal Request to Proposal (Stage 2 → Stage 3)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        # Only allocated officer or head can convert
        if pr['officer_id'] != user['officer_id'] and not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        if pr['status'] == 'CONVERTED_TO_PROPOSAL':
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=already_converted", status_code=302)

        proposal_number = generate_proposal_number(pr['office_id'])

        cursor.execute("""
            INSERT INTO proposals
            (proposal_number, pr_id, enquiry_id, client_name, client_type, domain, sub_domain,
             office_id, officer_id, description, estimated_value, status, approval_status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', 'PENDING', ?)
        """, (proposal_number, pr_id, pr['enquiry_id'], pr['client_name'], pr['client_type'],
              pr['domain'], pr['sub_domain'], pr['office_id'], pr['officer_id'],
              pr['description'], pr['estimated_value'], user['officer_id']))

        proposal_id = cursor.lastrowid

        cursor.execute("""
            UPDATE proposal_requests SET status = 'CONVERTED_TO_PROPOSAL', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (pr_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CONVERT', 'proposal_request', ?, ?)
        """, (user['officer_id'], pr_id, f"Converted to Proposal: {proposal_number}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{pr_id}/drop")
async def drop_proposal_request(request: Request, pr_id: int, drop_reason: str = Form(...)):
    """Mark proposal request as dropped."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        # Only head can drop
        if not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposal_requests SET
                status = 'DROPPED', drop_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (drop_reason, pr_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'DROP', 'proposal_request', ?, ?)
        """, (user['officer_id'], pr_id, f"Dropped: {drop_reason}"))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/hold")
async def hold_proposal_request(request: Request, pr_id: int):
    """Put proposal request on hold."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        if pr['officer_id'] != user['officer_id'] and not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposal_requests SET status = 'ON_HOLD', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (pr_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal_request', ?, 'Put on hold')
        """, (user['officer_id'], pr_id))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


@router.post("/{pr_id}/resume")
async def resume_proposal_request(request: Request, pr_id: int):
    """Resume proposal request from hold."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (pr_id,))
        pr = cursor.fetchone()

        if not pr:
            raise HTTPException(status_code=404, detail="Proposal Request not found")

        if pr['officer_id'] != user['officer_id'] and not is_office_head(user, pr['office_id']):
            return RedirectResponse(url=f"/proposal-request/{pr_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposal_requests SET status = 'IN_PROGRESS', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (pr_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal_request', ?, 'Resumed from hold')
        """, (user['officer_id'], pr_id))

    return RedirectResponse(url=f"/proposal-request/{pr_id}", status_code=302)


# Backward compatibility route
@router.post("/{pr_id}/cancel")
async def cancel_proposal_request(request: Request, pr_id: int, cancel_reason: str = Form(...)):
    """Cancel a proposal request (alias for drop)."""
    return await drop_proposal_request(request, pr_id, cancel_reason)
