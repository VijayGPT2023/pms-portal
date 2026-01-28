"""
Change Request routes: Officer → TL → Head approval flow.
Allows team members to request changes to milestone, cost, team, or revenue sharing.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user, is_admin, is_head, is_senior_management
from app.templates_config import templates

router = APIRouter()


def _get_assignment(cursor, assignment_id, ph):
    """Get assignment by ID."""
    cursor.execute(f"SELECT * FROM assignments WHERE id = {ph}", (assignment_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


@router.get("/new/{assignment_id}", response_class=HTMLResponse)
async def change_request_form(request: Request, assignment_id: int):
    """Display change request form for a team member officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'
    with get_db() as conn:
        cursor = conn.cursor()
        assignment = _get_assignment(cursor, assignment_id, ph)
        if not assignment:
            return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse(
        "change_request_form.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "error": request.query_params.get('error', '')
        }
    )


@router.post("/new/{assignment_id}")
async def submit_change_request(request: Request, assignment_id: int):
    """Submit a change request (Officer → TL for review)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form_data = await request.form()
    change_type = form_data.get('change_type', '')
    justification = form_data.get('justification', '').strip()
    details = form_data.get('details', '').strip()

    if not change_type or not justification:
        return RedirectResponse(
            url=f"/change-request/new/{assignment_id}?error=Change type and justification are required",
            status_code=302
        )

    valid_types = ('MILESTONE_CHANGE', 'COST_CHANGE', 'TEAM_CHANGE', 'REVENUE_CHANGE')
    if change_type not in valid_types:
        return RedirectResponse(
            url=f"/change-request/new/{assignment_id}?error=Invalid change type",
            status_code=302
        )

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        assignment = _get_assignment(cursor, assignment_id, ph)
        if not assignment:
            return RedirectResponse(url="/dashboard", status_code=302)

        # Create approval request with Officer→TL→Head flow
        import json
        request_data = json.dumps({
            "change_type": change_type,
            "details": details,
            "justification": justification
        })

        cursor.execute(f"""
            INSERT INTO approval_requests
            (request_type, reference_type, reference_id, requested_by, office_id, status,
             request_data, remarks, review_status)
            VALUES ('CHANGE_REQUEST', 'assignment', {ph}, {ph}, {ph}, 'PENDING',
                    {ph}, {ph}, 'PENDING')
        """, (
            assignment_id,
            user['officer_id'],
            assignment.get('office_id'),
            request_data,
            f'{change_type} request by {user["name"]}: {justification[:100]}'
        ))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'CREATE', 'change_request', {ph}, {ph})
        """, (user['officer_id'], assignment_id, f'Change request: {change_type}'))

    return RedirectResponse(
        url=f"/assignment/view/{assignment_id}?success=change_request_submitted",
        status_code=302
    )


@router.get("/review/{request_id}", response_class=HTMLResponse)
async def review_change_request(request: Request, request_id: int):
    """Display change request for TL to review."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT ar.*, a.assignment_no, a.title as assignment_title,
                   o.name as requested_by_name, o.designation as requester_designation
            FROM approval_requests ar
            JOIN assignments a ON ar.reference_id = a.id
            JOIN officers o ON ar.requested_by = o.officer_id
            WHERE ar.id = {ph}
        """, (request_id,))
        cr = cursor.fetchone()
        if not cr:
            return RedirectResponse(url="/approvals", status_code=302)
        cr = dict(cr)

    return templates.TemplateResponse(
        "change_request_review.html",
        {
            "request": request,
            "user": user,
            "change_request": cr,
            "error": request.query_params.get('error', '')
        }
    )


@router.post("/review/{request_id}/forward")
async def forward_change_request(request: Request, request_id: int,
                                  review_notes: str = Form("")):
    """TL reviews and forwards change request to Head."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE approval_requests
            SET review_status = 'FORWARDED',
                reviewed_by = {ph},
                review_notes = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], review_notes, request_id))

        # Get assignment_id for logging
        cursor.execute(f"SELECT reference_id FROM approval_requests WHERE id = {ph}", (request_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute(f"""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES ({ph}, 'FORWARD', 'change_request', {ph}, {ph})
            """, (user['officer_id'], row['reference_id'], f'TL forwarded change request to Head'))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/review/{request_id}/reject")
async def tl_reject_change_request(request: Request, request_id: int,
                                    review_notes: str = Form("")):
    """TL rejects the change request (doesn't forward to Head)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE approval_requests
            SET review_status = 'REJECTED',
                status = 'REJECTED',
                reviewed_by = {ph},
                review_notes = {ph},
                approval_remarks = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], review_notes, f'Rejected by TL: {review_notes}', request_id))

        cursor.execute(f"SELECT reference_id FROM approval_requests WHERE id = {ph}", (request_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute(f"""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES ({ph}, 'REJECT', 'change_request', {ph}, {ph})
            """, (user['officer_id'], row['reference_id'], f'TL rejected change request'))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/{request_id}/approve")
async def head_approve_change_request(request: Request, request_id: int):
    """Head approves a forwarded change request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        # Approve the request
        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'APPROVED',
                approved_by = {ph},
                approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], request_id))

        # Get change request details to apply changes
        cursor.execute(f"""
            SELECT reference_id, request_data FROM approval_requests WHERE id = {ph}
        """, (request_id,))
        cr = cursor.fetchone()
        if cr:
            import json
            try:
                data = json.loads(cr['request_data']) if cr['request_data'] else {}
            except:
                data = {}

            change_type = data.get('change_type', '')
            assignment_id = cr['reference_id']

            # Reset relevant section approval so TL can make the approved changes
            reset_map = {
                'MILESTONE_CHANGE': "milestone_approval_status = 'DRAFT'",
                'COST_CHANGE': "cost_approval_status = 'DRAFT'",
                'TEAM_CHANGE': "team_approval_status = 'DRAFT'",
                'REVENUE_CHANGE': "revenue_approval_status = 'DRAFT'",
            }

            if change_type in reset_map:
                cursor.execute(f"""
                    UPDATE assignments SET {reset_map[change_type]}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = {ph}
                """, (assignment_id,))

            cursor.execute(f"""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES ({ph}, 'APPROVE', 'change_request', {ph}, {ph})
            """, (user['officer_id'], assignment_id, f'Head approved change request: {change_type}'))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/{request_id}/reject")
async def head_reject_change_request(request: Request, request_id: int,
                                      rejection_remarks: str = Form("")):
    """Head rejects a forwarded change request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'REJECTED',
                approval_remarks = {ph},
                approved_by = {ph},
                approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, user['officer_id'], request_id))

        cursor.execute(f"SELECT reference_id FROM approval_requests WHERE id = {ph}", (request_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute(f"""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES ({ph}, 'REJECT', 'change_request', {ph}, {ph})
            """, (user['officer_id'], row['reference_id'], f'Head rejected change request'))

    return RedirectResponse(url="/approvals", status_code=302)
