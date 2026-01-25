"""
Approval workflow routes for managing assignment approvals, team allocations, etc.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.dependencies import get_current_user, is_admin, is_head, is_senior_management
from app.roles import (
    ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II,
    ROLE_RD_HEAD, ROLE_GROUP_HEAD, ROLE_TEAM_LEADER
)
from app.templates_config import templates

router = APIRouter()


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

        # ============================================================
        # NEW: Get pending Cost Estimation Approvals
        # ============================================================
        cursor.execute(f"""
            SELECT a.*, tl.name as tl_name, sub.name as submitted_by_name
            FROM assignments a
            LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
            LEFT JOIN officers sub ON a.cost_submitted_by = sub.officer_id
            WHERE a.cost_approval_status = 'SUBMITTED'
            {office_filter}
            ORDER BY a.cost_submitted_at DESC
        """, office_params)
        pending_cost_estimations = [dict(row) for row in cursor.fetchall()]

        # ============================================================
        # NEW: Get pending Team Constitution Approvals
        # ============================================================
        cursor.execute(f"""
            SELECT a.*, tl.name as tl_name, sub.name as submitted_by_name,
                   (SELECT COUNT(*) FROM assignment_team WHERE assignment_id = a.id) as team_count
            FROM assignments a
            LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
            LEFT JOIN officers sub ON a.team_submitted_by = sub.officer_id
            WHERE a.team_approval_status = 'SUBMITTED'
            {office_filter}
            ORDER BY a.team_submitted_at DESC
        """, office_params)
        pending_team_constitutions = [dict(row) for row in cursor.fetchall()]

        # ============================================================
        # NEW: Get pending Milestone Planning Approvals
        # ============================================================
        cursor.execute(f"""
            SELECT a.*, tl.name as tl_name, sub.name as submitted_by_name,
                   (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id) as milestone_count
            FROM assignments a
            LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
            LEFT JOIN officers sub ON a.milestone_submitted_by = sub.officer_id
            WHERE a.milestone_approval_status = 'SUBMITTED'
            {office_filter}
            ORDER BY a.milestone_submitted_at DESC
        """, office_params)
        pending_milestone_plans = [dict(row) for row in cursor.fetchall()]

        # ============================================================
        # NEW: Get pending Revenue Share Approvals
        # ============================================================
        cursor.execute(f"""
            SELECT a.*, tl.name as tl_name, sub.name as submitted_by_name,
                   (SELECT COUNT(*) FROM revenue_shares WHERE assignment_id = a.id) as share_count
            FROM assignments a
            LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
            LEFT JOIN officers sub ON a.revenue_submitted_by = sub.officer_id
            WHERE a.revenue_approval_status = 'SUBMITTED'
            {office_filter}
            ORDER BY a.revenue_submitted_at DESC
        """, office_params)
        pending_revenue_shares = [dict(row) for row in cursor.fetchall()]

        # Get pending revenue share change requests (old system)
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

        # Get pending milestone updates (old system)
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

        # ============================================================
        # NEW: Get pending Invoice Requests (for Finance role)
        # ============================================================
        cursor.execute(f"""
            SELECT ir.*, a.assignment_no, a.title, a.office_id,
                   o.name as requested_by_name
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            WHERE ir.status = 'PENDING'
            {office_filter}
            ORDER BY ir.created_at DESC
        """, office_params)
        pending_invoices = [dict(row) for row in cursor.fetchall()]

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

        # ============================================================
        # TRAINING: Get pending programme approvals
        # ============================================================
        cursor.execute(f"""
            SELECT tp.*, cb.name as created_by_name
            FROM training_programmes tp
            LEFT JOIN officers cb ON tp.created_by = cb.officer_id
            WHERE tp.approval_status = 'SUBMITTED'
            {office_filter.replace('a.office_id', 'tp.office_id')}
            ORDER BY tp.created_at DESC
        """, office_params)
        pending_training_programmes = [dict(row) for row in cursor.fetchall()]

        # TRAINING: Get programmes needing coordinator
        cursor.execute(f"""
            SELECT tp.*, cb.name as created_by_name
            FROM training_programmes tp
            LEFT JOIN officers cb ON tp.created_by = cb.officer_id
            WHERE (tp.coordinator_id IS NULL OR tp.coordinator_id = '')
            AND tp.approval_status IN ('APPROVED', 'DRAFT')
            {office_filter.replace('a.office_id', 'tp.office_id')}
            ORDER BY tp.created_at DESC
        """, office_params)
        unallocated_training = [dict(row) for row in cursor.fetchall()]

        # TRAINING: Get pending budget approvals
        cursor.execute(f"""
            SELECT tp.*, c.name as coordinator_name, sub.name as submitted_by_name
            FROM training_programmes tp
            LEFT JOIN officers c ON tp.coordinator_id = c.officer_id
            LEFT JOIN officers sub ON tp.budget_submitted_by = sub.officer_id
            WHERE tp.budget_approval_status = 'SUBMITTED'
            {office_filter.replace('a.office_id', 'tp.office_id')}
            ORDER BY tp.budget_submitted_at DESC
        """, office_params)
        pending_training_budget = [dict(row) for row in cursor.fetchall()]

        # TRAINING: Get pending trainer allocation approvals
        cursor.execute(f"""
            SELECT tp.*, c.name as coordinator_name, sub.name as submitted_by_name,
                   (SELECT COUNT(*) FROM trainer_allocations WHERE programme_id = tp.id) as trainer_count
            FROM training_programmes tp
            LEFT JOIN officers c ON tp.coordinator_id = c.officer_id
            LEFT JOIN officers sub ON tp.trainer_submitted_by = sub.officer_id
            WHERE tp.trainer_approval_status = 'SUBMITTED'
            {office_filter.replace('a.office_id', 'tp.office_id')}
            ORDER BY tp.trainer_submitted_at DESC
        """, office_params)
        pending_training_trainers = [dict(row) for row in cursor.fetchall()]

        # TRAINING: Get pending revenue share approvals
        cursor.execute(f"""
            SELECT tp.*, c.name as coordinator_name, sub.name as submitted_by_name,
                   (SELECT COUNT(*) FROM trainer_allocations WHERE programme_id = tp.id) as trainer_count
            FROM training_programmes tp
            LEFT JOIN officers c ON tp.coordinator_id = c.officer_id
            LEFT JOIN officers sub ON tp.revenue_submitted_by = sub.officer_id
            WHERE tp.revenue_approval_status = 'SUBMITTED'
            {office_filter.replace('a.office_id', 'tp.office_id')}
            ORDER BY tp.revenue_submitted_at DESC
        """, office_params)
        pending_training_revenue = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("approvals.html", {
        "request": request,
        "user": user,
        "pending_assignments": pending_assignments,
        "unallocated_assignments": unallocated_assignments,
        "pending_cost_estimations": pending_cost_estimations,
        "pending_team_constitutions": pending_team_constitutions,
        "pending_milestone_plans": pending_milestone_plans,
        "pending_revenue_shares": pending_revenue_shares,
        "pending_revenue": pending_revenue,
        "pending_milestones": pending_milestones,
        "pending_team": pending_team,
        "pending_invoices": pending_invoices,
        "office_officers": office_officers,
        # Training approvals
        "pending_training_programmes": pending_training_programmes,
        "unallocated_training": unallocated_training,
        "pending_training_budget": pending_training_budget,
        "pending_training_trainers": pending_training_trainers,
        "pending_training_revenue": pending_training_revenue
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


# ============================================================
# Cost Estimation Approval Workflow
# ============================================================

@router.post("/cost/{assignment_id}/submit")
async def submit_cost_estimation(request: Request, assignment_id: int):
    """TL submits cost estimation for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify user is TL of this assignment
        cursor.execute("""
            SELECT team_leader_officer_id FROM assignments WHERE id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            # Allow if user is head/admin
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if expenditure items exist
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM expenditure_items WHERE assignment_id = ?
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/assignment/expenditure/{assignment_id}?error=no_items", status_code=302)

        cursor.execute("""
            UPDATE assignments
            SET cost_approval_status = 'SUBMITTED',
                cost_submitted_by = ?,
                cost_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'cost_estimation', ?, 'Cost estimation submitted for approval')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?success=cost_submitted", status_code=302)


@router.post("/cost/{assignment_id}/approve")
async def approve_cost_estimation(request: Request, assignment_id: int):
    """Head approves cost estimation."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET cost_approval_status = 'APPROVED',
                cost_approved_by = ?,
                cost_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'cost_estimation', ?, 'Cost estimation approved')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/cost/{assignment_id}/reject")
async def reject_cost_estimation(request: Request, assignment_id: int,
                                  rejection_remarks: str = Form(...)):
    """Head rejects cost estimation."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET cost_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'cost_estimation', ?, ?)
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# ============================================================
# Team Constitution Approval Workflow
# ============================================================

@router.post("/team/{assignment_id}/submit")
async def submit_team_constitution(request: Request, assignment_id: int):
    """TL submits team constitution for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify user is TL of this assignment
        cursor.execute("""
            SELECT team_leader_officer_id FROM assignments WHERE id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if team members exist
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM assignment_team WHERE assignment_id = ?
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/revenue/edit/{assignment_id}?error=no_team", status_code=302)

        cursor.execute("""
            UPDATE assignments
            SET team_approval_status = 'SUBMITTED',
                team_submitted_by = ?,
                team_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'team_constitution', ?, 'Team constitution submitted for approval')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?success=team_submitted", status_code=302)


@router.post("/team/{assignment_id}/approve")
async def approve_team_constitution(request: Request, assignment_id: int):
    """Head approves team constitution."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET team_approval_status = 'APPROVED',
                team_approved_by = ?,
                team_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'team_constitution', ?, 'Team constitution approved')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/team/{assignment_id}/reject")
async def reject_team_constitution(request: Request, assignment_id: int,
                                   rejection_remarks: str = Form(...)):
    """Head rejects team constitution."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET team_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'team_constitution', ?, ?)
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# ============================================================
# Milestone Planning Approval Workflow
# ============================================================

@router.post("/milestone/{assignment_id}/submit")
async def submit_milestone_planning(request: Request, assignment_id: int):
    """TL submits milestone planning for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify user is TL of this assignment
        cursor.execute("""
            SELECT team_leader_officer_id FROM assignments WHERE id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if milestones exist
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM milestones WHERE assignment_id = ?
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/assignment/milestones/{assignment_id}?error=no_milestones", status_code=302)

        cursor.execute("""
            UPDATE assignments
            SET milestone_approval_status = 'SUBMITTED',
                milestone_submitted_by = ?,
                milestone_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'milestone_planning', ?, 'Milestone planning submitted for approval')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?success=milestone_submitted", status_code=302)


@router.post("/milestone/{assignment_id}/approve")
async def approve_milestone_planning(request: Request, assignment_id: int):
    """Head approves milestone planning."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET milestone_approval_status = 'APPROVED',
                milestone_approved_by = ?,
                milestone_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        # Also update all pending milestones to approved
        cursor.execute("""
            UPDATE milestones
            SET approval_status = 'APPROVED',
                updated_at = CURRENT_TIMESTAMP
            WHERE assignment_id = ? AND approval_status = 'PENDING'
        """, (assignment_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'milestone_planning', ?, 'Milestone planning approved')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/milestone/{assignment_id}/reject")
async def reject_milestone_planning(request: Request, assignment_id: int,
                                    rejection_remarks: str = Form(...)):
    """Head rejects milestone planning."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET milestone_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'milestone_planning', ?, ?)
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# ============================================================
# Revenue Share Approval Workflow
# ============================================================

@router.post("/revenue/{assignment_id}/submit")
async def submit_revenue_shares(request: Request, assignment_id: int):
    """TL submits revenue shares for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify user is TL of this assignment
        cursor.execute("""
            SELECT team_leader_officer_id FROM assignments WHERE id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if revenue shares exist
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM revenue_shares WHERE assignment_id = ?
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/revenue/edit/{assignment_id}?error=no_shares", status_code=302)

        # Verify total is 100%
        cursor.execute("""
            SELECT SUM(share_percent) as total FROM revenue_shares WHERE assignment_id = ?
        """, (assignment_id,))
        total = cursor.fetchone()['total'] or 0
        if abs(total - 100) > 0.01:
            return RedirectResponse(url=f"/revenue/edit/{assignment_id}?error=total_not_100", status_code=302)

        cursor.execute("""
            UPDATE assignments
            SET revenue_approval_status = 'SUBMITTED',
                revenue_submitted_by = ?,
                revenue_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'revenue_shares', ?, 'Revenue shares submitted for approval')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url=f"/assignment/view/{assignment_id}?success=revenue_submitted", status_code=302)


@router.post("/revenue/{assignment_id}/approve")
async def approve_revenue_shares(request: Request, assignment_id: int):
    """Head approves revenue shares."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET revenue_approval_status = 'APPROVED',
                revenue_approved_by = ?,
                revenue_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'revenue_shares', ?, 'Revenue shares approved')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/revenue/{assignment_id}/reject")
async def reject_revenue_shares(request: Request, assignment_id: int,
                                rejection_remarks: str = Form(...)):
    """Head rejects revenue shares."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET revenue_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, assignment_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'revenue_shares', ?, ?)
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)
