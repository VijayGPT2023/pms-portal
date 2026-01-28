"""
Approval workflow routes for managing assignment approvals, team allocations, etc.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db, USE_POSTGRES
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
    return await _approvals_page_inner(request, user)


async def _approvals_page_inner(request, user):
    with get_db() as conn:
        cursor = conn.cursor()

        # Determine which offices this user can approve for
        user_role = user.get('role', 'OFFICER')
        user_office = user.get('office_id')

        # Build office filter
        ph = '%s' if USE_POSTGRES else '?'
        if user_role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
            office_filter = ""
            office_params = []
        else:
            office_filter = f"AND a.office_id = {ph}"
            office_params = [user_office]

        # ============================================================
        # WORKFLOW: Get pending registrations (new activities awaiting approval)
        # ============================================================
        cursor.execute(f"""
            SELECT a.*, reg.name as registered_by_name
            FROM assignments a
            LEFT JOIN officers reg ON a.registered_by = reg.officer_id
            WHERE a.registration_status = 'PENDING_APPROVAL'
            {office_filter}
            ORDER BY a.created_at DESC
        """, office_params)
        pending_registrations = [dict(row) for row in cursor.fetchall()]

        # ============================================================
        # WORKFLOW: Get approved registrations needing TL assignment
        # ============================================================
        cursor.execute(f"""
            SELECT a.*, reg.name as registered_by_name
            FROM assignments a
            LEFT JOIN officers reg ON a.registered_by = reg.officer_id
            WHERE a.workflow_stage = 'TL_ASSIGNMENT'
            AND (a.team_leader_officer_id IS NULL OR a.team_leader_officer_id = '')
            {office_filter}
            ORDER BY a.created_at DESC
        """, office_params)
        pending_tl_assignments = [dict(row) for row in cursor.fetchall()]

        # Get pending assignments (DRAFT status, needs approval - legacy)
        cursor.execute(f"""
            SELECT a.*, o.name as created_by_name
            FROM assignments a
            LEFT JOIN officers o ON a.team_leader_officer_id = o.officer_id
            WHERE a.approval_status = 'DRAFT'
            AND (a.registration_status IS NULL OR a.registration_status NOT IN ('PENDING_APPROVAL', 'APPROVED'))
            {office_filter}
            ORDER BY a.created_at DESC
        """, office_params)
        pending_assignments = [dict(row) for row in cursor.fetchall()]

        # Get assignments without team leader (need allocation - legacy)
        cursor.execute(f"""
            SELECT a.*, o.name as created_by_name
            FROM assignments a
            LEFT JOIN officers o ON a.team_leader_officer_id = o.officer_id
            WHERE (a.team_leader_officer_id IS NULL OR a.team_leader_officer_id = '')
            AND a.approval_status IN ('APPROVED', 'DRAFT')
            AND (a.workflow_stage IS NULL OR a.workflow_stage NOT IN ('REGISTRATION', 'TL_ASSIGNMENT'))
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
        # TRAINING: Get pending programme approvals (tables may not exist yet)
        # ============================================================
        pending_training_programmes = []
        unallocated_training = []
        pending_training_budget = []
        pending_training_trainers = []
        pending_training_revenue = []

        # Check if training_programmes table exists before querying
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'training_programmes'
            )
        """ if USE_POSTGRES else """
            SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='training_programmes'
        """)
        training_table_exists = cursor.fetchone()[0] if USE_POSTGRES else cursor.fetchone()['cnt'] > 0

        if training_table_exists:
            cursor.execute(f"""
                SELECT tp.*, cb.name as created_by_name
                FROM training_programmes tp
                LEFT JOIN officers cb ON tp.created_by = cb.officer_id
                WHERE tp.approval_status = 'SUBMITTED'
                {office_filter.replace('a.office_id', 'tp.office_id')}
                ORDER BY tp.created_at DESC
            """, office_params)
            pending_training_programmes = [dict(row) for row in cursor.fetchall()]

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

        # ============================================================
        # CHANGE REQUESTS: Pending TL review (for TL users)
        # ============================================================
        cursor.execute(f"""
            SELECT ar.*, a.assignment_no, a.title as assignment_title,
                   o.name as requested_by_name
            FROM approval_requests ar
            JOIN assignments a ON ar.reference_id = a.id
            JOIN officers o ON ar.requested_by = o.officer_id
            WHERE ar.request_type = 'CHANGE_REQUEST'
            AND ar.review_status = 'PENDING'
            AND ar.status = 'PENDING'
            {office_filter.replace('a.office_id', 'ar.office_id')}
            ORDER BY ar.created_at DESC
        """, office_params)
        pending_cr_tl_review = [dict(row) for row in cursor.fetchall()]

        # ============================================================
        # CHANGE REQUESTS: Forwarded by TL, pending Head approval
        # ============================================================
        cursor.execute(f"""
            SELECT ar.*, a.assignment_no, a.title as assignment_title,
                   o.name as requested_by_name, tl.name as reviewed_by_name
            FROM approval_requests ar
            JOIN assignments a ON ar.reference_id = a.id
            JOIN officers o ON ar.requested_by = o.officer_id
            LEFT JOIN officers tl ON ar.reviewed_by = tl.officer_id
            WHERE ar.request_type = 'CHANGE_REQUEST'
            AND ar.review_status = 'FORWARDED'
            AND ar.status = 'PENDING'
            {office_filter.replace('a.office_id', 'ar.office_id')}
            ORDER BY ar.created_at DESC
        """, office_params)
        pending_cr_head_approval = [dict(row) for row in cursor.fetchall()]

        # ============================================================
        # Get pending Tentative Date Change Requests
        # ============================================================
        cursor.execute(f"""
            SELECT m.*, a.assignment_no, a.title as assignment_title, a.office_id,
                   o.name as requested_by_name
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            LEFT JOIN officers o ON m.tentative_date_requested_by = o.officer_id
            WHERE m.tentative_date_status = 'PENDING'
            {office_filter}
            ORDER BY m.tentative_date_requested_at DESC
        """, office_params)
        pending_tentative_dates = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("approvals.html", {
        "request": request,
        "user": user,
        "pending_registrations": pending_registrations,
        "pending_tl_assignments": pending_tl_assignments,
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
        "pending_tentative_dates": pending_tentative_dates,
        "pending_cr_tl_review": pending_cr_tl_review,
        "pending_cr_head_approval": pending_cr_head_approval,
        "office_officers": office_officers,
        # Training approvals
        "pending_training_programmes": pending_training_programmes,
        "unallocated_training": unallocated_training,
        "pending_training_budget": pending_training_budget,
        "pending_training_trainers": pending_training_trainers,
        "pending_training_revenue": pending_training_revenue
    })


# ============================================================
# Helper: Check if all 5 sections approved → set ACTIVE
# ============================================================

def _check_all_sections_approved(cursor, assignment_id, ph):
    """Check if all 5 sections are approved. If so, advance to ACTIVE."""
    cursor.execute(f"""
        SELECT approval_status, cost_approval_status, team_approval_status,
               milestone_approval_status, revenue_approval_status, workflow_stage
        FROM assignments WHERE id = {ph}
    """, (assignment_id,))
    row = cursor.fetchone()
    if not row:
        return

    all_approved = (
        row['approval_status'] == 'APPROVED' and
        row['cost_approval_status'] == 'APPROVED' and
        row['team_approval_status'] == 'APPROVED' and
        row['milestone_approval_status'] == 'APPROVED' and
        row['revenue_approval_status'] == 'APPROVED'
    )

    if all_approved and row['workflow_stage'] in ('DETAIL_ENTRY', None, ''):
        cursor.execute(f"""
            UPDATE assignments
            SET workflow_stage = 'ACTIVE', status = 'Ongoing', updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (assignment_id,))


# ============================================================
# Registration Approval Workflow
# ============================================================

@router.post("/registration/{assignment_id}/approve")
async def approve_registration(request: Request, assignment_id: int):
    """Head approves a new activity registration."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET registration_status = 'APPROVED',
                workflow_stage = 'TL_ASSIGNMENT',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (assignment_id,))

        # Update related approval_request
        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'APPROVED', approved_by = {ph}, approved_at = CURRENT_TIMESTAMP
            WHERE reference_id = {ph} AND request_type = 'REGISTRATION' AND status = 'PENDING'
        """, (user['officer_id'], assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'registration', {ph}, 'Activity registration approved')
        """, (user['officer_id'], assignment_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/registration/{assignment_id}/reject")
async def reject_registration(request: Request, assignment_id: int,
                               rejection_remarks: str = Form(...)):
    """Head rejects a new activity registration."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET registration_status = 'REJECTED',
                remarks = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, assignment_id))

        # Update related approval_request
        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'REJECTED', approval_remarks = {ph}, approved_by = {ph}, approved_at = CURRENT_TIMESTAMP
            WHERE reference_id = {ph} AND request_type = 'REGISTRATION' AND status = 'PENDING'
        """, (rejection_remarks, user['officer_id'], assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'registration', {ph}, {ph})
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/assignment/{assignment_id}/approve")
async def approve_assignment(request: Request, assignment_id: int):
    """Approve an assignment (basic info section)."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET approval_status = 'APPROVED', updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (assignment_id,))

        # Check if all sections are approved → advance to ACTIVE
        _check_all_sections_approved(cursor, assignment_id, ph)

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'assignment', {ph}, 'Assignment approved')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET approval_status = 'REJECTED', remarks = {ph}, updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, assignment_id))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'assignment', {ph}, {ph})
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
        ph = '%s' if USE_POSTGRES else '?'

        # Update assignment with team leader and advance workflow
        cursor.execute(f"""
            UPDATE assignments
            SET team_leader_officer_id = {ph},
                workflow_stage = CASE
                    WHEN workflow_stage = 'TL_ASSIGNMENT' THEN 'DETAIL_ENTRY'
                    ELSE COALESCE(workflow_stage, 'DETAIL_ENTRY')
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (team_leader_id, assignment_id))

        # Add to assignment_team table
        if USE_POSTGRES:
            cursor.execute(f"""
                INSERT INTO assignment_team (assignment_id, officer_id, role, assigned_by)
                VALUES ({ph}, {ph}, 'TEAM_LEADER', {ph})
                ON CONFLICT (assignment_id, officer_id) DO UPDATE SET role = 'TEAM_LEADER', assigned_by = EXCLUDED.assigned_by
            """, (assignment_id, team_leader_id, user['officer_id']))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO assignment_team (assignment_id, officer_id, role, assigned_by)
                VALUES (?, ?, 'TEAM_LEADER', ?)
            """, (assignment_id, team_leader_id, user['officer_id']))

        # Update the team leader's role if not already set
        cursor.execute(f"""
            UPDATE officers SET admin_role_id = 'TEAM_LEADER'
            WHERE officer_id = {ph} AND (admin_role_id IS NULL OR admin_role_id = '')
        """, (team_leader_id,))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES ({ph}, 'UPDATE', 'assignment', {ph}, {ph}, 'Team leader allocated')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'APPROVED', approved_by = {ph}, approved_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], request_id))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'request', {ph}, 'Request approved')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'REJECTED', approval_remarks = {ph}, approved_by = {ph},
                approved_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, user['officer_id'], request_id))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'request', {ph}, {ph})
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE approval_requests
            SET status = 'ESCALATED', escalated_to = {ph}, escalated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (escalate_to, request_id))

        # Log the action
        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES ({ph}, 'ESCALATE', 'request', {ph}, {ph}, 'Request escalated')
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
        ph = '%s' if USE_POSTGRES else '?'

        # Verify user is TL of this assignment
        cursor.execute(f"""
            SELECT team_leader_officer_id FROM assignments WHERE id = {ph}
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            # Allow if user is head/admin
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if expenditure items exist
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM expenditure_items WHERE assignment_id = {ph}
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/assignment/expenditure/{assignment_id}?error=no_items", status_code=302)

        cursor.execute(f"""
            UPDATE assignments
            SET cost_approval_status = 'SUBMITTED',
                cost_submitted_by = {ph},
                cost_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'SUBMIT', 'cost_estimation', {ph}, 'Cost estimation submitted for approval')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET cost_approval_status = 'APPROVED',
                cost_approved_by = {ph},
                cost_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        _check_all_sections_approved(cursor, assignment_id, ph)

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'cost_estimation', {ph}, 'Cost estimation approved')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET cost_approval_status = 'REJECTED',
                remarks = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'cost_estimation', {ph}, {ph})
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
        ph = '%s' if USE_POSTGRES else '?'

        # Verify user is TL of this assignment
        cursor.execute(f"""
            SELECT team_leader_officer_id FROM assignments WHERE id = {ph}
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if team members exist
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM assignment_team WHERE assignment_id = {ph}
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/revenue/edit/{assignment_id}?error=no_team", status_code=302)

        cursor.execute(f"""
            UPDATE assignments
            SET team_approval_status = 'SUBMITTED',
                team_submitted_by = {ph},
                team_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'SUBMIT', 'team_constitution', {ph}, 'Team constitution submitted for approval')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET team_approval_status = 'APPROVED',
                team_approved_by = {ph},
                team_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        _check_all_sections_approved(cursor, assignment_id, ph)

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'team_constitution', {ph}, 'Team constitution approved')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET team_approval_status = 'REJECTED',
                remarks = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'team_constitution', {ph}, {ph})
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
        ph = '%s' if USE_POSTGRES else '?'

        # Verify user is TL of this assignment
        cursor.execute(f"""
            SELECT team_leader_officer_id FROM assignments WHERE id = {ph}
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if milestones exist
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM milestones WHERE assignment_id = {ph}
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/assignment/milestones/{assignment_id}?error=no_milestones", status_code=302)

        cursor.execute(f"""
            UPDATE assignments
            SET milestone_approval_status = 'SUBMITTED',
                milestone_submitted_by = {ph},
                milestone_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'SUBMIT', 'milestone_planning', {ph}, 'Milestone planning submitted for approval')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET milestone_approval_status = 'APPROVED',
                milestone_approved_by = {ph},
                milestone_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        # Also update all pending milestones to approved
        cursor.execute(f"""
            UPDATE milestones
            SET approval_status = 'APPROVED',
                updated_at = CURRENT_TIMESTAMP
            WHERE assignment_id = {ph} AND approval_status = 'PENDING'
        """, (assignment_id,))

        _check_all_sections_approved(cursor, assignment_id, ph)

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'milestone_planning', {ph}, 'Milestone planning approved')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET milestone_approval_status = 'REJECTED',
                remarks = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'milestone_planning', {ph}, {ph})
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
        ph = '%s' if USE_POSTGRES else '?'

        # Verify user is TL of this assignment
        cursor.execute(f"""
            SELECT team_leader_officer_id FROM assignments WHERE id = {ph}
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Check if revenue shares exist
        cursor.execute(f"""
            SELECT COUNT(*) as cnt FROM revenue_shares WHERE assignment_id = {ph}
        """, (assignment_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/revenue/edit/{assignment_id}?error=no_shares", status_code=302)

        # Verify total is 100%
        cursor.execute(f"""
            SELECT SUM(share_percent) as total FROM revenue_shares WHERE assignment_id = {ph}
        """, (assignment_id,))
        total = cursor.fetchone()['total'] or 0
        if abs(total - 100) > 0.01:
            return RedirectResponse(url=f"/revenue/edit/{assignment_id}?error=total_not_100", status_code=302)

        cursor.execute(f"""
            UPDATE assignments
            SET revenue_approval_status = 'SUBMITTED',
                revenue_submitted_by = {ph},
                revenue_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'SUBMIT', 'revenue_shares', {ph}, 'Revenue shares submitted for approval')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET revenue_approval_status = 'APPROVED',
                revenue_approved_by = {ph},
                revenue_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], assignment_id))

        _check_all_sections_approved(cursor, assignment_id, ph)

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'APPROVE', 'revenue_shares', {ph}, 'Revenue shares approved')
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
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE assignments
            SET revenue_approval_status = 'REJECTED',
                remarks = {ph},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (rejection_remarks, assignment_id))

        cursor.execute(f"""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES ({ph}, 'REJECT', 'revenue_shares', {ph}, {ph})
        """, (user['officer_id'], assignment_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# ============================================================
# Tentative Date Change Approval Routes
# ============================================================

@router.post("/tentative-date/{milestone_id}/approve")
async def approve_tentative_date(request: Request, milestone_id: int):
    """Head approves tentative date change request."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        cursor.execute(f"""
            UPDATE milestones
            SET tentative_date_status = 'APPROVED',
                tentative_date_approved_by = {ph},
                tentative_date_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {ph}
        """, (user['officer_id'], milestone_id))

        # Get assignment_id for logging
        cursor.execute(f"SELECT assignment_id FROM milestones WHERE id = {ph}", (milestone_id,))
        milestone = cursor.fetchone()
        if milestone:
            cursor.execute(f"""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES ({ph}, 'APPROVE', 'tentative_date', {ph}, 'Tentative date change approved')
            """, (user['officer_id'], milestone['assignment_id']))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/tentative-date/{milestone_id}/reject")
async def reject_tentative_date(request: Request, milestone_id: int,
                                rejection_remarks: str = Form("")):
    """Head rejects tentative date change request."""
    user, redirect = require_approver_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'

        # Get the original target_date to revert tentative_date
        cursor.execute(f"SELECT assignment_id, target_date FROM milestones WHERE id = {ph}", (milestone_id,))
        milestone = cursor.fetchone()

        if milestone:
            cursor.execute(f"""
                UPDATE milestones
                SET tentative_date = {ph},
                    tentative_date_status = 'REJECTED',
                    tentative_date_approved_by = {ph},
                    tentative_date_approved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = {ph}
            """, (milestone['target_date'], user['officer_id'], milestone_id))

            cursor.execute(f"""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES ({ph}, 'REJECT', 'tentative_date', {ph}, {ph})
            """, (user['officer_id'], milestone['assignment_id'], rejection_remarks or 'Tentative date change rejected'))

    return RedirectResponse(url="/approvals", status_code=302)
