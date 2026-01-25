"""
Approval workflow routes for managing assignment approvals, team allocations, etc.
"""
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.dependencies import get_current_user, is_admin, is_head, is_senior_management
from app.roles import (
    ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II,
    ROLE_RD_HEAD, ROLE_GROUP_HEAD, ROLE_TEAM_LEADER
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def require_approver_access(request: Request):
    """Check if user can approve (Head, DDG, DG, or Admin)."""
    user = get_current_user(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=302)
    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return None, RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)
    return user, None


@router.get("", response_class=HTMLResponse)
async def approvals_page(request: Request):
    """Display pending approvals page."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        # Determine which offices this user can approve for
        user_role = user.get('role', 'OFFICER')
        user_office = user.get('office_id')

        # Build office filter
        if user_role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
            office_filter = ""
            office_params = []
        else:
            office_filter = "AND a.office_id = ?"
            office_params = [user_office]

        # Get pending assignments (DRAFT status, needs approval)
        cursor.execute(f"""
            SELECT a.*, o.name as created_by_name
            FROM assignments a
            LEFT JOIN officers o ON a.team_leader_officer_id = o.officer_id
            WHERE a.approval_status = 'DRAFT'
            {office_filter}
            ORDER BY a.created_at DESC
        """, office_params)
        pending_assignments = [dict(row) for row in cursor.fetchall()]

        # Get assignments without team leader (need allocation)
        cursor.execute(f"""
            SELECT a.*, o.name as created_by_name
            FROM assignments a
            LEFT JOIN officers o ON a.team_leader_officer_id = o.officer_id
            WHERE (a.team_leader_officer_id IS NULL OR a.team_leader_officer_id = '')
            AND a.approval_status IN ('APPROVED', 'DRAFT')
            {office_filter}
            ORDER BY a.created_at DESC
        """, office_params)
        unallocated_assignments = [dict(row) for row in cursor.fetchall()]

        # Get pending revenue share requests
        cursor.execute(f"""
            SELECT r.*, a.assignment_no, o.name as requested_by_name,
                   rs.share_percent as current_share
            FROM approval_requests r
            JOIN assignments a ON r.reference_id = a.id
            JOIN officers o ON r.requested_by = o.officer_id
            LEFT JOIN revenue_shares rs ON r.reference_id = rs.assignment_id
                                        AND r.requested_by = rs.officer_id
            WHERE r.request_type = 'REVENUE_SHARE_CHANGE'
            AND r.status = 'PENDING'
            {office_filter.replace('a.office_id', 'r.office_id')}
            ORDER BY r.created_at DESC
        """, office_params)
        pending_revenue = [dict(row) for row in cursor.fetchall()]

        # Get pending milestone updates
        cursor.execute(f"""
            SELECT m.*, a.assignment_no, a.office_id
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.approval_status = 'PENDING'
            {office_filter}
            ORDER BY m.updated_at DESC
        """, office_params)
        pending_milestones = [dict(row) for row in cursor.fetchall()]

        # Get pending team allocations
        pending_team = []  # For future use

        # Get officers by office for team leader allocation dropdown
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers
            WHERE is_active = 1
            ORDER BY office_id, name
        """)
        all_officers = [dict(row) for row in cursor.fetchall()]

        office_officers = {}
        for officer in all_officers:
            oid = officer['office_id']
            if oid not in office_officers:
                office_officers[oid] = []
            office_officers[oid].append(officer)

    return templates.TemplateResponse("approvals.html", {
        "request": request,
        "user": user,
        "pending_assignments": pending_assignments,
        "unallocated_assignments": unallocated_assignments,
        "pending_revenue": pending_revenue,
        "pending_milestones": pending_milestones,
        "pending_team": pending_team,
        "office_officers": office_officers
    })


@router.post("/assignment/{assignment_id}/approve")
async def approve_assignment(request: Request, assignment_id: int):
    """Approve an assignment."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET approval_status = 'APPROVED', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (assignment_id,))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'assignment', ?, 'Assignment approved')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/assignment/{assignment_id}/reject")
async def reject_assignment(request: Request, assignment_id: int,
                            rejection_remarks: str = Form(...)):
    """Reject an assignment."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET approval_status = 'REJECTED', remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, assignment_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'assignment', ?, ?)
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/allocate-tl/{assignment_id}")
async def allocate_team_leader(request: Request, assignment_id: int,
                                team_leader_id: str = Form(...)):
    """Allocate a team leader to an assignment."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        # Update assignment with team leader
        cursor.execute("""
            UPDATE assignments
            SET team_leader_officer_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (team_leader_id, assignment_id))

        # Add to assignment_team table
        cursor.execute("""
            INSERT OR REPLACE INTO assignment_team (assignment_id, officer_id, role, assigned_by)
            VALUES (?, ?, 'TEAM_LEADER', ?)
        """, (assignment_id, team_leader_id, user['officer_id']))

        # Update the team leader's role if not already set
        cursor.execute("""
            UPDATE officers SET admin_role_id = 'TEAM_LEADER'
            WHERE officer_id = ? AND (admin_role_id IS NULL OR admin_role_id = '')
        """, (team_leader_id,))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'UPDATE', 'assignment', ?, ?, 'Team leader allocated')
        """, (user['officer_id'], assignment_id, f"team_leader={team_leader_id}"))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/request/{request_id}/approve")
async def approve_request(request: Request, request_id: int):
    """Approve a request (revenue share change, etc.)."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE approval_requests
            SET status = 'APPROVED', approved_by = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], request_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'request', ?, 'Request approved')
        """, (user['officer_id'], request_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/request/{request_id}/reject")
async def reject_request(request: Request, request_id: int,
                         rejection_remarks: str = Form(...)):
    """Reject a request."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE approval_requests
            SET status = 'REJECTED', approval_remarks = ?, approved_by = ?,
                approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, user['officer_id'], request_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'request', ?, ?)
        """, (user['officer_id'], request_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/request/{request_id}/escalate")
async def escalate_request(request: Request, request_id: int,
                           escalate_to: str = Form(...)):
    """Escalate a request to higher authority."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE approval_requests
            SET status = 'ESCALATED', escalated_to = ?, escalated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (escalate_to, request_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'ESCALATE', 'request', ?, ?, 'Request escalated')
        """, (user['officer_id'], request_id, f"escalated_to={escalate_to}"))

    return RedirectResponse(url="/approvals", status_code=302)
