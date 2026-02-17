"""
Routes for Utilization Claims System (Feature 3F).
Workflow: Officer fills → Submits → TL Approves → Head Rectifies → FINAL
"""
from datetime import datetime, date
import calendar

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user
from app.templates_config import templates
from app.config import DEV_WORK_QUANTIFICATION, UTILIZATION_CLAIM_TYPES

router = APIRouter()

CLAIM_TYPES = [ct[0] for ct in UTILIZATION_CLAIM_TYPES]
CLAIM_TYPE_LABELS = {ct[0]: ct[1] for ct in UTILIZATION_CLAIM_TYPES}
VALID_STATUSES = ['DRAFT', 'SUBMITTED', 'TL_APPROVED', 'HEAD_RECTIFIED', 'FINAL']
STATUS_LABELS = {
    'DRAFT': 'Draft', 'SUBMITTED': 'Submitted', 'TL_APPROVED': 'TL Approved',
    'HEAD_RECTIFIED': 'Head Rectified', 'FINAL': 'Final'
}


def calculate_auto_days(claim_type, proposal_value=0, num_members=0, requested_days=0):
    """Auto-calculate man-days based on claim type and parameters."""
    if claim_type == 'PROPOSAL_PREP':
        for threshold, days in DEV_WORK_QUANTIFICATION['PROPOSAL_PREP']['slabs']:
            if proposal_value <= threshold:
                return days
        return 5
    elif claim_type == 'EVENT_MGMT':
        return min(requested_days, DEV_WORK_QUANTIFICATION['EVENT_MGMT']['max_days'])
    elif claim_type == 'COMMITTEE':
        return num_members * DEV_WORK_QUANTIFICATION['COMMITTEE']['per_member_days']
    elif claim_type == 'MEETING':
        return max(requested_days, DEV_WORK_QUANTIFICATION['MEETING']['min_days'])
    return requested_days


def _is_tl_for_officer(cursor, user, officer_id):
    """Check if user is TL for assignments where officer is a member."""
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM assignments a
        JOIN assignment_team at2 ON a.id = at2.assignment_id
        WHERE a.team_leader_officer_id = ? AND at2.officer_id = ? AND at2.is_active = 1
    """, (user['officer_id'], officer_id))
    result = cursor.fetchone()
    return result and result['cnt'] > 0


def _is_head_for_officer(cursor, user, officer_id):
    """Check if user is office head for the officer."""
    from app.roles import get_user_role, ROLE_RD_HEAD, ROLE_GROUP_HEAD, ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II
    role = get_user_role(user)
    if role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
        return True
    if role in [ROLE_RD_HEAD, ROLE_GROUP_HEAD]:
        cursor.execute("SELECT office_id FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        return officer and officer['office_id'] == user.get('office_id')
    return False


def _get_working_days(year, month):
    """Calculate working days (weekdays) in a month."""
    num_days = calendar.monthrange(year, month)[1]
    return sum(1 for d in range(1, num_days + 1) if date(year, month, d).weekday() < 5)


# ─────────────────────────────────────────────
# 1. List My Claims
# ─────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def utilization_list(request: Request, month: str = None, status: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        conditions = ["uc.officer_id = ?"]
        params = [user['officer_id']]

        if month:
            conditions.append("uc.claim_month = ?")
            params.append(month)
        if status:
            conditions.append("uc.status = ?")
            params.append(status)

        where = " AND ".join(conditions)
        cursor.execute(f"""
            SELECT uc.*, a.title as assignment_title, a.assignment_no
            FROM utilization_claims uc
            LEFT JOIN assignments a ON uc.assignment_id = a.id
            WHERE {where}
            ORDER BY uc.activity_date DESC
        """, params)
        claims = cursor.fetchall()

    return templates.TemplateResponse("utilization_list.html", {
        "request": request, "user": user, "claims": claims,
        "filter_month": month, "filter_status": status,
        "claim_type_labels": CLAIM_TYPE_LABELS, "status_labels": STATUS_LABELS,
    })


# ─────────────────────────────────────────────
# 2. New Claim Form
# ─────────────────────────────────────────────
@router.get("/new", response_class=HTMLResponse)
async def new_claim_form(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.assignment_no, a.title FROM assignments a
            LEFT JOIN assignment_team at2 ON a.id = at2.assignment_id AND at2.officer_id = ?
            WHERE (a.team_leader_officer_id = ? OR at2.officer_id = ? OR a.registered_by = ?)
            AND a.status IN ('Not Started', 'Ongoing', 'In Progress')
            ORDER BY a.title
        """, (user['officer_id'], user['officer_id'], user['officer_id'], user['officer_id']))
        assignments = cursor.fetchall()

    return templates.TemplateResponse("utilization_form.html", {
        "request": request, "user": user, "claim": None,
        "assignments": assignments, "claim_types": UTILIZATION_CLAIM_TYPES,
        "is_edit": False,
    })


# ─────────────────────────────────────────────
# 3. Create New Claim
# ─────────────────────────────────────────────
@router.post("/new")
async def create_claim(request: Request,
                       assignment_id: int = Form(None),
                       activity_date: str = Form(...),
                       claim_type: str = Form(...),
                       man_days_claimed: float = Form(0),
                       activity_description: str = Form(""),
                       proposal_value_lakhs: float = Form(0),
                       num_committee_members: int = Form(0),
                       event_duration_days: float = Form(0)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if claim_type not in CLAIM_TYPES:
        raise HTTPException(status_code=400, detail="Invalid claim type")

    # Auto-calculate man-days for specific types
    if claim_type in ['PROPOSAL_PREP', 'EVENT_MGMT', 'COMMITTEE', 'MEETING']:
        man_days_claimed = calculate_auto_days(
            claim_type, proposal_value_lakhs, num_committee_members, event_duration_days
        )

    # Derive claim_month from activity_date
    try:
        act_date = datetime.strptime(activity_date, '%Y-%m-%d').date()
        claim_month = act_date.strftime('%Y-%m')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    from app.database import generate_utilization_claim_number
    claim_number = generate_utilization_claim_number(user['officer_id'], claim_month)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO utilization_claims (
                claim_number, officer_id, assignment_id, claim_month, activity_date,
                man_days_claimed, activity_description, claim_type, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT')
        """, (claim_number, user['officer_id'], assignment_id if assignment_id else None,
              claim_month, activity_date, man_days_claimed,
              activity_description.strip() if activity_description else None, claim_type))

    return RedirectResponse(url="/utilization/", status_code=302)


# ─────────────────────────────────────────────
# 4. Edit Claim Form
# ─────────────────────────────────────────────
@router.get("/{claim_id}/edit", response_class=HTMLResponse)
async def edit_claim_form(request: Request, claim_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND officer_id = ?",
                       (claim_id, user['officer_id']))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        if claim['status'] != 'DRAFT':
            raise HTTPException(status_code=400, detail="Only DRAFT claims can be edited")

        cursor.execute("""
            SELECT a.id, a.assignment_no, a.title FROM assignments a
            LEFT JOIN assignment_team at2 ON a.id = at2.assignment_id AND at2.officer_id = ?
            WHERE (a.team_leader_officer_id = ? OR at2.officer_id = ? OR a.registered_by = ?)
            AND a.status IN ('Not Started', 'Ongoing', 'In Progress')
            ORDER BY a.title
        """, (user['officer_id'], user['officer_id'], user['officer_id'], user['officer_id']))
        assignments = cursor.fetchall()

    return templates.TemplateResponse("utilization_form.html", {
        "request": request, "user": user, "claim": claim,
        "assignments": assignments, "claim_types": UTILIZATION_CLAIM_TYPES,
        "is_edit": True,
    })


# ─────────────────────────────────────────────
# 5. Update Claim
# ─────────────────────────────────────────────
@router.post("/{claim_id}/edit")
async def update_claim(request: Request, claim_id: int,
                       assignment_id: int = Form(None),
                       activity_date: str = Form(...),
                       claim_type: str = Form(...),
                       man_days_claimed: float = Form(0),
                       activity_description: str = Form(""),
                       proposal_value_lakhs: float = Form(0),
                       num_committee_members: int = Form(0),
                       event_duration_days: float = Form(0)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND officer_id = ?",
                       (claim_id, user['officer_id']))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        if claim['status'] != 'DRAFT':
            raise HTTPException(status_code=400, detail="Only DRAFT claims can be edited")

    if claim_type in ['PROPOSAL_PREP', 'EVENT_MGMT', 'COMMITTEE', 'MEETING']:
        man_days_claimed = calculate_auto_days(
            claim_type, proposal_value_lakhs, num_committee_members, event_duration_days
        )

    try:
        act_date = datetime.strptime(activity_date, '%Y-%m-%d').date()
        claim_month = act_date.strftime('%Y-%m')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE utilization_claims SET
                assignment_id = ?, activity_date = ?, claim_month = ?,
                claim_type = ?, man_days_claimed = ?, activity_description = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (assignment_id if assignment_id else None, activity_date, claim_month,
              claim_type, man_days_claimed,
              activity_description.strip() if activity_description else None, claim_id))

    return RedirectResponse(url="/utilization/", status_code=302)


# ─────────────────────────────────────────────
# 6. Submit Claim (DRAFT → SUBMITTED)
# ─────────────────────────────────────────────
@router.post("/{claim_id}/submit")
async def submit_claim(request: Request, claim_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND officer_id = ?",
                       (claim_id, user['officer_id']))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        if claim['status'] != 'DRAFT':
            raise HTTPException(status_code=400, detail="Only DRAFT claims can be submitted")

        cursor.execute("""
            UPDATE utilization_claims SET status = 'SUBMITTED',
                submitted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (claim_id,))

    return RedirectResponse(url="/utilization/", status_code=302)


# ─────────────────────────────────────────────
# 7. TL: Pending Approval List
# ─────────────────────────────────────────────
@router.get("/pending-approval", response_class=HTMLResponse)
async def pending_approval(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        # Get officers where current user is TL
        cursor.execute("""
            SELECT DISTINCT uc.*, o.name as officer_name, a.title as assignment_title,
                   a.assignment_no
            FROM utilization_claims uc
            JOIN officers o ON uc.officer_id = o.officer_id
            LEFT JOIN assignments a ON uc.assignment_id = a.id
            WHERE uc.status = 'SUBMITTED'
            AND (
                EXISTS (
                    SELECT 1 FROM assignments a2
                    JOIN assignment_team at2 ON a2.id = at2.assignment_id
                    WHERE a2.team_leader_officer_id = ? AND at2.officer_id = uc.officer_id AND at2.is_active = 1
                )
                OR EXISTS (
                    SELECT 1 FROM officer_roles WHERE officer_id = ?
                    AND role_type IN ('RD_HEAD', 'GROUP_HEAD')
                    AND (effective_to IS NULL OR effective_to >= DATE('now'))
                )
            )
            ORDER BY uc.submitted_at DESC
        """, (user['officer_id'], user['officer_id']))
        claims = cursor.fetchall()

    return templates.TemplateResponse("utilization_pending.html", {
        "request": request, "user": user, "claims": claims,
        "claim_type_labels": CLAIM_TYPE_LABELS,
    })


# ─────────────────────────────────────────────
# 8. TL: Approve Claim (SUBMITTED → TL_APPROVED)
# ─────────────────────────────────────────────
@router.post("/{claim_id}/tl-approve")
async def tl_approve(request: Request, claim_id: int, remarks: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND status = 'SUBMITTED'",
                       (claim_id,))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found or not in SUBMITTED status")

        if not _is_tl_for_officer(cursor, user, claim['officer_id']):
            from app.roles import is_head, is_admin
            if not is_head(user) and not is_admin(user):
                raise HTTPException(status_code=403, detail="Not authorized")

        cursor.execute("""
            UPDATE utilization_claims SET status = 'TL_APPROVED',
                tl_approved_by = ?, tl_approved_at = CURRENT_TIMESTAMP,
                tl_remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], remarks.strip() if remarks else None, claim_id))

    return RedirectResponse(url="/utilization/pending-approval", status_code=302)


# ─────────────────────────────────────────────
# 9. TL: Reject Claim (SUBMITTED → DRAFT)
# ─────────────────────────────────────────────
@router.post("/{claim_id}/tl-reject")
async def tl_reject(request: Request, claim_id: int, remarks: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND status = 'SUBMITTED'",
                       (claim_id,))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        cursor.execute("""
            UPDATE utilization_claims SET status = 'DRAFT',
                tl_remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (remarks.strip(), claim_id))

    return RedirectResponse(url="/utilization/pending-approval", status_code=302)


# ─────────────────────────────────────────────
# 10. Head: Pending Rectification List
# ─────────────────────────────────────────────
@router.get("/pending-rectification", response_class=HTMLResponse)
async def pending_rectification(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.roles import get_user_role, ROLE_RD_HEAD, ROLE_GROUP_HEAD, ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II
    role = get_user_role(user)

    with get_db() as conn:
        cursor = conn.cursor()

        if role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
            cursor.execute("""
                SELECT uc.*, o.name as officer_name, a.title as assignment_title,
                       a.assignment_no
                FROM utilization_claims uc
                JOIN officers o ON uc.officer_id = o.officer_id
                LEFT JOIN assignments a ON uc.assignment_id = a.id
                WHERE uc.status = 'TL_APPROVED'
                ORDER BY uc.tl_approved_at DESC
            """)
        elif role in [ROLE_RD_HEAD, ROLE_GROUP_HEAD]:
            cursor.execute("""
                SELECT uc.*, o.name as officer_name, a.title as assignment_title,
                       a.assignment_no
                FROM utilization_claims uc
                JOIN officers o ON uc.officer_id = o.officer_id
                LEFT JOIN assignments a ON uc.assignment_id = a.id
                WHERE uc.status = 'TL_APPROVED' AND o.office_id = ?
                ORDER BY uc.tl_approved_at DESC
            """, (user['office_id'],))
        else:
            return RedirectResponse(url="/utilization/", status_code=302)

        claims = cursor.fetchall()

    return templates.TemplateResponse("utilization_rectification.html", {
        "request": request, "user": user, "claims": claims,
        "claim_type_labels": CLAIM_TYPE_LABELS,
    })


# ─────────────────────────────────────────────
# 11. Head: Rectify Claim (TL_APPROVED → HEAD_RECTIFIED)
# ─────────────────────────────────────────────
@router.post("/{claim_id}/head-rectify")
async def head_rectify(request: Request, claim_id: int,
                       rectified_days: float = Form(...),
                       remarks: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND status = 'TL_APPROVED'",
                       (claim_id,))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        if not _is_head_for_officer(cursor, user, claim['officer_id']):
            raise HTTPException(status_code=403, detail="Not authorized")

        cursor.execute("""
            UPDATE utilization_claims SET status = 'HEAD_RECTIFIED',
                rectified_days = ?, head_rectified_by = ?,
                head_rectified_at = CURRENT_TIMESTAMP,
                head_remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rectified_days, user['officer_id'],
              remarks.strip() if remarks else None, claim_id))

    return RedirectResponse(url="/utilization/pending-rectification", status_code=302)


# ─────────────────────────────────────────────
# 12. Head: Finalize Claim (HEAD_RECTIFIED → FINAL)
# ─────────────────────────────────────────────
@router.post("/{claim_id}/finalize")
async def finalize_claim(request: Request, claim_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM utilization_claims WHERE id = ? AND status = 'HEAD_RECTIFIED'",
                       (claim_id,))
        claim = cursor.fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        if not _is_head_for_officer(cursor, user, claim['officer_id']):
            raise HTTPException(status_code=403, detail="Not authorized")

        cursor.execute("""
            UPDATE utilization_claims SET status = 'FINAL', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (claim_id,))

    return RedirectResponse(url="/utilization/pending-rectification", status_code=302)


# ─────────────────────────────────────────────
# 13. Utilization Summary MIS
# ─────────────────────────────────────────────
@router.get("/summary", response_class=HTMLResponse)
async def utilization_summary(request: Request, month: str = None, office: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not month:
        month = date.today().strftime('%Y-%m')

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["uc.claim_month = ?"]
        params = [month]

        from app.roles import get_user_role, ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II, ROLE_RD_HEAD, ROLE_GROUP_HEAD
        role = get_user_role(user)

        if office and role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
            conditions.append("o.office_id = ?")
            params.append(office)
        elif role in [ROLE_RD_HEAD, ROLE_GROUP_HEAD]:
            conditions.append("o.office_id = ?")
            params.append(user['office_id'])

        where = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT o.officer_id, o.name as officer_name, o.office_id,
                   COALESCE(SUM(uc.man_days_claimed), 0) as total_claimed,
                   COALESCE(SUM(CASE WHEN uc.status IN ('TL_APPROVED','HEAD_RECTIFIED','FINAL')
                                     THEN uc.man_days_claimed ELSE 0 END), 0) as total_approved,
                   COALESCE(SUM(CASE WHEN uc.status IN ('HEAD_RECTIFIED','FINAL')
                                     THEN COALESCE(uc.rectified_days, uc.man_days_claimed) ELSE 0 END), 0) as total_rectified,
                   COUNT(uc.id) as claim_count
            FROM officers o
            LEFT JOIN utilization_claims uc ON o.officer_id = uc.officer_id AND {where}
            WHERE o.is_active = 1
            GROUP BY o.officer_id, o.name, o.office_id
            HAVING claim_count > 0
            ORDER BY o.name
        """, params)
        summary = cursor.fetchall()

        # Get offices for filter
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = cursor.fetchall()

    # Calculate working days for the month
    try:
        year, mon = int(month.split('-')[0]), int(month.split('-')[1])
        working_days = _get_working_days(year, mon)
    except:
        working_days = 22

    return templates.TemplateResponse("utilization_summary.html", {
        "request": request, "user": user, "summary": summary,
        "filter_month": month, "filter_office": office,
        "offices": offices, "working_days": working_days,
    })
