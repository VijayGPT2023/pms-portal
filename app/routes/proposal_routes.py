"""
Routes for Proposal Management (Stage 3 of 4-stage workflow).
Workflow: Any officer creates → Head approves/allocates → Officer works → Submit/Win/Lose

Enquiry → Proposal Request → Proposal → Work Order
"""
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.dependencies import get_current_user
from app.config import TEMPLATES_DIR

router = APIRouter(prefix="/proposal", tags=["proposal"])
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


def can_edit_proposal(user, proposal):
    """Check if user can edit this proposal."""
    # Creator can edit if pending approval
    if proposal.get('created_by') == user['officer_id'] and proposal.get('approval_status') == 'PENDING':
        return True
    # Allocated officer can update progress
    if proposal.get('officer_id') == user['officer_id']:
        return True
    # Head can always edit
    if is_office_head(user, proposal.get('office_id')):
        return True
    return False


@router.get("/", response_class=HTMLResponse)
async def list_proposals(request: Request, status: str = None, office: str = None, view: str = None):
    """List all proposals with filters."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["1=1"]
        params = []

        if status:
            conditions.append("p.status = ?")
            params.append(status)

        if office:
            conditions.append("p.office_id = ?")
            params.append(office)

        # View filters
        admin_role = user.get('admin_role_id', '')
        if view == 'pending_approval' and admin_role in ['ADMIN', 'DG', 'DDG', 'HEAD']:
            conditions.append("p.approval_status = 'PENDING'")
        elif view == 'my_created':
            conditions.append("p.created_by = ?")
            params.append(user['officer_id'])
        elif view == 'my_allocated':
            conditions.append("p.officer_id = ?")
            params.append(user['officer_id'])
        elif admin_role not in ['ADMIN', 'DG', 'DDG']:
            # Regular users see their office's proposals
            conditions.append("p.office_id = ?")
            params.append(user['office_id'])

        where_clause = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT p.*, o.name as officer_name, off.office_name,
                   pr.pr_number, e.enquiry_number, creator.name as created_by_name,
                   approver.name as approved_by_name
            FROM proposals p
            LEFT JOIN officers o ON p.officer_id = o.officer_id
            LEFT JOIN offices off ON p.office_id = off.office_id
            LEFT JOIN proposal_requests pr ON p.pr_id = pr.id
            LEFT JOIN enquiries e ON p.enquiry_id = e.id
            LEFT JOIN officers creator ON p.created_by = creator.officer_id
            LEFT JOIN officers approver ON p.approved_by = approver.officer_id
            WHERE {where_clause}
            ORDER BY p.created_at DESC
        """, params)
        proposals = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT status, COUNT(*) as count FROM proposals
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Pending approval count for heads
        cursor.execute("SELECT COUNT(*) as count FROM proposals WHERE approval_status = 'PENDING'")
        pending_approval_count = cursor.fetchone()['count']

    # Check if user is a head (can approve)
    is_head = is_office_head(user, user.get('office_id'))

    return templates.TemplateResponse("proposal_list.html", {
        "request": request,
        "user": user,
        "proposals": proposals,
        "offices": offices,
        "status_counts": status_counts,
        "pending_approval_count": pending_approval_count,
        "filter_status": status,
        "filter_office": office,
        "filter_view": view,
        "is_head": is_head
    })


@router.get("/new", response_class=HTMLResponse)
async def new_proposal_form(request: Request, from_pr: int = None):
    """Display form to create new proposal - accessible by any logged-in officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    source_pr = None
    if from_pr:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (from_pr,))
            row = cursor.fetchone()
            if row:
                source_pr = dict(row)

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

    return templates.TemplateResponse("proposal_form.html", {
        "request": request,
        "user": user,
        "officers": officers,
        "offices": offices,
        "domains": domains,
        "client_types": client_types,
        "proposal": source_pr,  # Pre-fill from PR if available
        "mode": "new",
        "from_pr": from_pr,
        "is_head": is_office_head(user, user.get('office_id'))
    })


@router.post("/create")
async def create_proposal(
    request: Request,
    client_name: str = Form(...),
    client_type: str = Form(None),
    domain: str = Form(None),
    sub_domain: str = Form(None),
    office_id: str = Form(...),
    officer_id: str = Form(None),
    description: str = Form(None),
    estimated_value: float = Form(None),
    proposed_value: float = Form(None),
    target_date: str = Form(None),
    remarks: str = Form(None),
    from_pr: int = Form(None)
):
    """Create a new proposal - any officer can create, pending Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.database import generate_proposal_number
    proposal_number = generate_proposal_number(office_id)

    # If creator is a Head, auto-approve
    is_head = is_office_head(user, office_id)
    initial_status = 'APPROVED' if is_head else 'PENDING_APPROVAL'
    approval_status = 'APPROVED' if is_head else 'PENDING'

    # Get enquiry_id from PR if available
    enquiry_id = None
    if from_pr:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT enquiry_id FROM proposal_requests WHERE id = ?", (from_pr,))
            row = cursor.fetchone()
            if row:
                enquiry_id = row['enquiry_id']

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO proposals
            (proposal_number, pr_id, enquiry_id, client_name, client_type, domain, sub_domain,
             office_id, officer_id, description, estimated_value, proposed_value, target_date,
             remarks, status, approval_status, approved_by, approved_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (proposal_number, from_pr, enquiry_id, client_name, client_type, domain, sub_domain,
              office_id, officer_id if is_head else None, description, estimated_value, proposed_value,
              target_date, remarks, initial_status, approval_status,
              user['officer_id'] if is_head else None,
              'CURRENT_TIMESTAMP' if is_head else None,
              user['officer_id']))

        proposal_id = cursor.lastrowid

        # If created from PR, update PR status
        if from_pr:
            cursor.execute("""
                UPDATE proposal_requests SET status = 'CONVERTED_TO_PROPOSAL', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (from_pr,))

        # Log activity
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CREATE', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Created proposal {proposal_number}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.get("/{proposal_id}", response_class=HTMLResponse)
async def view_proposal(request: Request, proposal_id: int):
    """View proposal details."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT p.*, o.name as officer_name, off.office_name,
                   pr.pr_number, e.enquiry_number, creator.name as created_by_name,
                   approver.name as approved_by_name
            FROM proposals p
            LEFT JOIN officers o ON p.officer_id = o.officer_id
            LEFT JOIN offices off ON p.office_id = off.office_id
            LEFT JOIN proposal_requests pr ON p.pr_id = pr.id
            LEFT JOIN enquiries e ON p.enquiry_id = e.id
            LEFT JOIN officers creator ON p.created_by = creator.officer_id
            LEFT JOIN officers approver ON p.approved_by = approver.officer_id
            WHERE p.id = ?
        """, (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        proposal = dict(proposal)

        # Check if converted to Assignment (Work Order)
        cursor.execute("""
            SELECT * FROM assignments WHERE proposal_id = ?
        """, (proposal_id,))
        linked_assignment = cursor.fetchone()
        if linked_assignment:
            proposal['linked_assignment'] = dict(linked_assignment)

        # Get source PR and Enquiry details
        if proposal.get('pr_id'):
            cursor.execute("SELECT * FROM proposal_requests WHERE id = ?", (proposal['pr_id'],))
            pr = cursor.fetchone()
            if pr:
                proposal['pr'] = dict(pr)

        if proposal.get('enquiry_id'):
            cursor.execute("SELECT * FROM enquiries WHERE id = ?", (proposal['enquiry_id'],))
            enq = cursor.fetchone()
            if enq:
                proposal['enquiry'] = dict(enq)

        # Get activity log
        cursor.execute("""
            SELECT al.*, o.name as actor_name
            FROM activity_log al
            LEFT JOIN officers o ON al.actor_id = o.officer_id
            WHERE al.entity_type = 'proposal' AND al.entity_id = ?
            ORDER BY al.created_at DESC
        """, (proposal_id,))
        activities = [dict(row) for row in cursor.fetchall()]

        # Get officers for allocation dropdown (if head)
        cursor.execute("""
            SELECT officer_id, name, office_id FROM officers
            WHERE is_active = 1 ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

    # Check permissions
    can_edit = can_edit_proposal(user, proposal)
    is_head = is_office_head(user, proposal.get('office_id'))
    is_allocated_officer = proposal.get('officer_id') == user['officer_id']
    is_creator = proposal.get('created_by') == user['officer_id']

    return templates.TemplateResponse("proposal_view.html", {
        "request": request,
        "user": user,
        "proposal": proposal,
        "activities": activities,
        "officers": officers,
        "can_edit": can_edit,
        "is_head": is_head,
        "is_allocated_officer": is_allocated_officer,
        "is_creator": is_creator
    })


@router.get("/{proposal_id}/edit", response_class=HTMLResponse)
async def edit_proposal_form(request: Request, proposal_id: int):
    """Display form to edit proposal."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        proposal = dict(proposal)

        if not can_edit_proposal(user, proposal):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("SELECT officer_id, name, office_id FROM officers WHERE is_active = 1 ORDER BY name")
        officers = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT option_value, option_label FROM config_options WHERE category = 'domain' AND is_active = 1")
        domains = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT option_value, option_label FROM config_options WHERE category = 'client_type' AND is_active = 1")
        client_types = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("proposal_form.html", {
        "request": request,
        "user": user,
        "proposal": proposal,
        "officers": officers,
        "offices": offices,
        "domains": domains,
        "client_types": client_types,
        "mode": "edit",
        "is_head": is_office_head(user, proposal.get('office_id'))
    })


@router.post("/{proposal_id}/update")
async def update_proposal(
    request: Request,
    proposal_id: int,
    client_name: str = Form(...),
    client_type: str = Form(None),
    domain: str = Form(None),
    sub_domain: str = Form(None),
    office_id: str = Form(...),
    officer_id: str = Form(None),
    description: str = Form(None),
    estimated_value: float = Form(None),
    proposed_value: float = Form(None),
    target_date: str = Form(None),
    remarks: str = Form(None)
):
    """Update an existing proposal."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()
        if not proposal or not can_edit_proposal(user, dict(proposal)):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET
                client_name = ?, client_type = ?, domain = ?, sub_domain = ?,
                office_id = ?, officer_id = ?, description = ?, estimated_value = ?,
                proposed_value = ?, target_date = ?, remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (client_name, client_type, domain, sub_domain, office_id, officer_id,
              description, estimated_value, proposed_value, target_date, remarks, proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, 'Updated proposal details')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/approve")
async def approve_proposal(request: Request, proposal_id: int, officer_id: str = Form(...)):
    """Head approves proposal and allocates to an officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET
                status = 'APPROVED', approval_status = 'APPROVED',
                officer_id = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (officer_id, user['officer_id'], proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'proposal', ?, 'Approved and allocated to officer')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/reject")
async def reject_proposal(request: Request, proposal_id: int, rejection_reason: str = Form(...)):
    """Head rejects proposal."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET
                status = 'REJECTED', approval_status = 'REJECTED',
                rejection_reason = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_reason, user['officer_id'], proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Rejected: {rejection_reason}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/reallocate")
async def reallocate_proposal(request: Request, proposal_id: int, officer_id: str = Form(...)):
    """Head reallocates proposal to a different officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        old_officer = proposal['officer_id']
        cursor.execute("""
            UPDATE proposals SET officer_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (officer_id, proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REALLOCATE', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Reallocated from {old_officer} to {officer_id}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/update-progress")
async def update_progress(request: Request, proposal_id: int, current_update: str = Form(...), status: str = Form(None)):
    """Allocated officer updates progress on the proposal."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        # Only allocated officer or head can update progress
        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        new_status = status if status else proposal['status']
        if new_status == 'APPROVED':
            new_status = 'IN_PROGRESS'  # Move to in-progress once work starts

        cursor.execute("""
            UPDATE proposals SET
                current_update = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (current_update, new_status, proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Progress update: {current_update[:100]}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/submit")
async def submit_proposal(request: Request, proposal_id: int):
    """Mark proposal as submitted to client."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET status = 'SUBMITTED', submission_date = DATE('now'),
                   updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (proposal_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, 'Proposal submitted to client')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/shortlist")
async def shortlist_proposal(request: Request, proposal_id: int):
    """Mark proposal as shortlisted."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET status = 'SHORTLISTED', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (proposal_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, 'Proposal shortlisted')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/under-review")
async def mark_under_review(request: Request, proposal_id: int):
    """Mark proposal as under review by client."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET status = 'UNDER_REVIEW', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (proposal_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, 'Proposal marked as under review')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/mark-won")
async def mark_proposal_won(request: Request, proposal_id: int, work_order_value: float = Form(...)):
    """Mark proposal as won and create Work Order (Assignment)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        if proposal['status'] == 'WON':
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=already_won", status_code=302)

        # Generate assignment number
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM assignments
            WHERE office_id = ? AND strftime('%Y', created_at) = strftime('%Y', 'now')
        """, (proposal['office_id'],))
        next_num = cursor.fetchone()['next_num']

        from datetime import datetime
        year = datetime.now().year
        assignment_number = f"WO/{proposal['office_id']}/{year}/{next_num:04d}"

        # Create Assignment from Proposal
        cursor.execute("""
            INSERT INTO assignments
            (assignment_number, proposal_id, client_name, domain, sub_domain,
             office_id, description, sanctioned_value, assignment_type, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'REVENUE', 'ACTIVE', ?)
        """, (assignment_number, proposal_id, proposal['client_name'], proposal['domain'],
              proposal['sub_domain'], proposal['office_id'], proposal['description'],
              work_order_value, user['officer_id']))

        assignment_id = cursor.lastrowid

        # Update proposal status
        cursor.execute("""
            UPDATE proposals SET status = 'WON', work_order_value = ?,
                   updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (work_order_value, proposal_id))

        # Log activity
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CONVERT', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Won - Created Work Order: {assignment_number}"))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}", status_code=302)


@router.post("/{proposal_id}/mark-lost")
async def mark_proposal_lost(request: Request, proposal_id: int, loss_reason: str = Form(...)):
    """Mark proposal as lost."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET
                status = 'LOST', loss_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (loss_reason, proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Lost: {loss_reason}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/withdraw")
async def withdraw_proposal(request: Request, proposal_id: int, withdraw_reason: str = Form(...)):
    """Withdraw a proposal."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET
                status = 'WITHDRAWN', withdraw_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (withdraw_reason, proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Withdrawn: {withdraw_reason}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/drop")
async def drop_proposal(request: Request, proposal_id: int, drop_reason: str = Form(...)):
    """Mark proposal as dropped (by Head only)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        # Only head can drop
        if not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET
                status = 'DROPPED', drop_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (drop_reason, proposal_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'DROP', 'proposal', ?, ?)
        """, (user['officer_id'], proposal_id, f"Dropped: {drop_reason}"))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/hold")
async def hold_proposal(request: Request, proposal_id: int):
    """Put proposal on hold."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET status = 'ON_HOLD', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (proposal_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, 'Put on hold')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)


@router.post("/{proposal_id}/resume")
async def resume_proposal(request: Request, proposal_id: int):
    """Resume proposal from hold."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        proposal = cursor.fetchone()

        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if proposal['officer_id'] != user['officer_id'] and not is_office_head(user, proposal['office_id']):
            return RedirectResponse(url=f"/proposal/{proposal_id}?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE proposals SET status = 'IN_PROGRESS', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (proposal_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'proposal', ?, 'Resumed from hold')
        """, (user['officer_id'], proposal_id))

    return RedirectResponse(url=f"/proposal/{proposal_id}", status_code=302)
