"""
Training Programme routes: CRUD and approval workflows.
Manages training programmes, trainer allocations, and participants.
"""
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user, is_admin, is_head, is_senior_management
from app.templates_config import templates

router = APIRouter()


def generate_programme_number(office_id: str) -> str:
    """Generate unique programme number: TRN-OFFICE-YYYYMM-NNN"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = date.today()
        prefix = f"TRN-{office_id}-{today.strftime('%Y%m')}"

        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_num FROM training_programmes
                WHERE programme_number LIKE %s
            """, (f"{prefix}%",))
        else:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_num FROM training_programmes
                WHERE programme_number LIKE ?
            """, (f"{prefix}%",))

        next_num = cursor.fetchone()['next_num']
        return f"{prefix}-{next_num:03d}"


def is_training_coordinator(user, programme):
    """Check if user is coordinator of the training programme."""
    return programme.get('coordinator_id') == user['officer_id']


@router.get("", response_class=HTMLResponse)
async def training_list(request: Request):
    """Display list of training programmes."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get training programmes
        if is_admin(user) or is_senior_management(user):
            cursor.execute("""
                SELECT tp.*, o.name as coordinator_name, off.office_name
                FROM training_programmes tp
                LEFT JOIN officers o ON tp.coordinator_id = o.officer_id
                LEFT JOIN offices off ON tp.office_id = off.office_id
                ORDER BY tp.created_at DESC
            """)
        else:
            cursor.execute("""
                SELECT tp.*, o.name as coordinator_name, off.office_name
                FROM training_programmes tp
                LEFT JOIN officers o ON tp.coordinator_id = o.officer_id
                LEFT JOIN offices off ON tp.office_id = off.office_id
                WHERE tp.office_id = ? OR tp.coordinator_id = ?
                   OR tp.id IN (SELECT programme_id FROM trainer_allocations WHERE officer_id = ?)
                ORDER BY tp.created_at DESC
            """, (user['office_id'], user['officer_id'], user['officer_id']))

        programmes = [dict(row) for row in cursor.fetchall()]

        # Get summary stats
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN stage = 'ANNOUNCED' THEN 1 END) as announced,
                COUNT(CASE WHEN stage = 'REGISTRATION_OPEN' THEN 1 END) as registration_open,
                COUNT(CASE WHEN stage = 'CONDUCTED' THEN 1 END) as conducted,
                COUNT(CASE WHEN stage = 'CLOSED' THEN 1 END) as closed,
                COALESCE(SUM(budgeted_revenue), 0) as total_budgeted,
                COALESCE(SUM(actual_revenue), 0) as total_actual
            FROM training_programmes
        """)
        stats = dict(cursor.fetchone())

    return templates.TemplateResponse("training_list.html", {
        "request": request,
        "user": user,
        "programmes": programmes,
        "stats": stats
    })


@router.get("/create", response_class=HTMLResponse)
async def training_create_form(request: Request):
    """Display training programme creation form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get offices
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        # Get officers for coordinator selection
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers WHERE is_active = 1
            ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("training_form.html", {
        "request": request,
        "user": user,
        "programme": None,
        "offices": offices,
        "officers": officers,
        "is_new": True
    })


@router.post("/create")
async def training_create(
    request: Request,
    title: str = Form(...),
    topic_domain: str = Form(""),
    description: str = Form(""),
    office_id: str = Form(...),
    mode: str = Form("IN_PERSON"),
    location: str = Form(""),
    venue_details: str = Form(""),
    training_start_date: str = Form(""),
    training_end_date: str = Form(""),
    duration_days: int = Form(0),
    budgeted_participants: int = Form(0),
    fee_per_participant: float = Form(0),
    application_start_date: str = Form(""),
    application_end_date: str = Form(""),
    remarks: str = Form("")
):
    """Create a new training programme."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        programme_number = generate_programme_number(office_id)
        budgeted_revenue = budgeted_participants * fee_per_participant

        cursor.execute("""
            INSERT INTO training_programmes
            (programme_number, title, topic_domain, description, office_id, mode,
             location, venue_details, training_start_date, training_end_date,
             duration_days, budgeted_participants, fee_per_participant, budgeted_revenue,
             application_start_date, application_end_date, remarks, created_by,
             stage, approval_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ANNOUNCED', 'DRAFT')
        """, (
            programme_number, title, topic_domain, description, office_id, mode,
            location, venue_details,
            training_start_date if training_start_date else None,
            training_end_date if training_end_date else None,
            duration_days, budgeted_participants, fee_per_participant, budgeted_revenue,
            application_start_date if application_start_date else None,
            application_end_date if application_end_date else None,
            remarks, user['officer_id']
        ))

        programme_id = cursor.lastrowid

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CREATE', 'training_programme', ?, 'Training programme created')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}", status_code=302)


@router.get("/view/{programme_id}", response_class=HTMLResponse)
async def training_view(request: Request, programme_id: int):
    """View training programme details."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get programme details
        cursor.execute("""
            SELECT tp.*, o.name as coordinator_name, off.office_name,
                   cb.name as created_by_name
            FROM training_programmes tp
            LEFT JOIN officers o ON tp.coordinator_id = o.officer_id
            LEFT JOIN offices off ON tp.office_id = off.office_id
            LEFT JOIN officers cb ON tp.created_by = cb.officer_id
            WHERE tp.id = ?
        """, (programme_id,))
        programme = cursor.fetchone()
        if not programme:
            return RedirectResponse(url="/training", status_code=302)

        programme = dict(programme)

        # Get trainer allocations
        cursor.execute("""
            SELECT ta.*, o.name as trainer_name, o.designation
            FROM trainer_allocations ta
            JOIN officers o ON ta.officer_id = o.officer_id
            WHERE ta.programme_id = ?
            ORDER BY ta.trainer_role, o.name
        """, (programme_id,))
        trainers = [dict(row) for row in cursor.fetchall()]

        # Get participants
        cursor.execute("""
            SELECT * FROM training_participants
            WHERE programme_id = ?
            ORDER BY registration_date DESC
        """, (programme_id,))
        participants = [dict(row) for row in cursor.fetchall()]

        # Check if user can edit
        can_edit = (
            is_admin(user) or
            is_head(user) or
            programme['coordinator_id'] == user['officer_id'] or
            programme['created_by'] == user['officer_id']
        )

    return templates.TemplateResponse("training_view.html", {
        "request": request,
        "user": user,
        "programme": programme,
        "trainers": trainers,
        "participants": participants,
        "can_edit": can_edit
    })


@router.get("/edit/{programme_id}", response_class=HTMLResponse)
async def training_edit_form(request: Request, programme_id: int):
    """Display training programme edit form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM training_programmes WHERE id = ?", (programme_id,))
        programme = cursor.fetchone()
        if not programme:
            return RedirectResponse(url="/training", status_code=302)

        programme = dict(programme)

        # Get offices
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        # Get officers
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers WHERE is_active = 1
            ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("training_form.html", {
        "request": request,
        "user": user,
        "programme": programme,
        "offices": offices,
        "officers": officers,
        "is_new": False
    })


@router.post("/edit/{programme_id}")
async def training_edit(
    request: Request,
    programme_id: int,
    title: str = Form(...),
    topic_domain: str = Form(""),
    description: str = Form(""),
    office_id: str = Form(...),
    mode: str = Form("IN_PERSON"),
    location: str = Form(""),
    venue_details: str = Form(""),
    training_start_date: str = Form(""),
    training_end_date: str = Form(""),
    duration_days: int = Form(0),
    budgeted_participants: int = Form(0),
    fee_per_participant: float = Form(0),
    application_start_date: str = Form(""),
    application_end_date: str = Form(""),
    stage: str = Form("ANNOUNCED"),
    remarks: str = Form("")
):
    """Update training programme."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        budgeted_revenue = budgeted_participants * fee_per_participant

        cursor.execute("""
            UPDATE training_programmes SET
                title = ?, topic_domain = ?, description = ?, office_id = ?, mode = ?,
                location = ?, venue_details = ?, training_start_date = ?, training_end_date = ?,
                duration_days = ?, budgeted_participants = ?, fee_per_participant = ?,
                budgeted_revenue = ?, application_start_date = ?, application_end_date = ?,
                stage = ?, remarks = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            title, topic_domain, description, office_id, mode,
            location, venue_details,
            training_start_date if training_start_date else None,
            training_end_date if training_end_date else None,
            duration_days, budgeted_participants, fee_per_participant, budgeted_revenue,
            application_start_date if application_start_date else None,
            application_end_date if application_end_date else None,
            stage, remarks, programme_id
        ))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'training_programme', ?, 'Training programme updated')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}", status_code=302)


@router.get("/trainers/{programme_id}", response_class=HTMLResponse)
async def trainer_allocation_form(request: Request, programme_id: int):
    """Display trainer allocation form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM training_programmes WHERE id = ?", (programme_id,))
        programme = cursor.fetchone()
        if not programme:
            return RedirectResponse(url="/training", status_code=302)

        programme = dict(programme)

        # Get existing trainers
        cursor.execute("""
            SELECT ta.*, o.name as trainer_name, o.designation
            FROM trainer_allocations ta
            JOIN officers o ON ta.officer_id = o.officer_id
            WHERE ta.programme_id = ?
            ORDER BY ta.trainer_role, o.name
        """, (programme_id,))
        trainers = [dict(row) for row in cursor.fetchall()]

        # Get all officers
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers WHERE is_active = 1
            ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("trainer_allocation_form.html", {
        "request": request,
        "user": user,
        "programme": programme,
        "trainers": trainers,
        "officers": officers
    })


@router.post("/trainers/{programme_id}")
async def save_trainer_allocations(request: Request, programme_id: int):
    """Save trainer allocations."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()

    with get_db() as conn:
        cursor = conn.cursor()

        # Delete existing allocations
        cursor.execute("DELETE FROM trainer_allocations WHERE programme_id = ?", (programme_id,))

        # Insert new allocations
        i = 0
        while f"trainer_{i}_officer_id" in form:
            officer_id = form.get(f"trainer_{i}_officer_id")
            if officer_id:
                trainer_role = form.get(f"trainer_{i}_role", "CO_TRAINER")
                allocation_percent = float(form.get(f"trainer_{i}_percent", 0) or 0)
                allocation_days = int(form.get(f"trainer_{i}_days", 0) or 0)

                cursor.execute("""
                    INSERT INTO trainer_allocations
                    (programme_id, officer_id, trainer_role, allocation_percent, allocation_days)
                    VALUES (?, ?, ?, ?, ?)
                """, (programme_id, officer_id, trainer_role, allocation_percent, allocation_days))
            i += 1

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'UPDATE', 'trainer_allocations', ?, 'Trainer allocations updated')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}?success=trainers_saved", status_code=302)


# ============================================================
# Training Approval Workflow Routes
# ============================================================

@router.post("/approve/{programme_id}")
async def approve_training_programme(request: Request, programme_id: int):
    """Head approves training programme."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET approval_status = 'APPROVED',
                approved_by = ?,
                approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'training_programme', ?, 'Training programme approved')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/reject/{programme_id}")
async def reject_training_programme(
    request: Request,
    programme_id: int,
    rejection_remarks: str = Form(...)
):
    """Head rejects training programme."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'training_programme', ?, ?)
        """, (user['officer_id'], programme_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/allocate-coordinator/{programme_id}")
async def allocate_coordinator(
    request: Request,
    programme_id: int,
    coordinator_id: str = Form(...)
):
    """Head allocates coordinator to training programme."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET coordinator_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (coordinator_id, programme_id))

        # Also add as PRIMARY trainer if not exists
        cursor.execute("""
            INSERT INTO trainer_allocations (programme_id, officer_id, trainer_role, allocation_percent)
            SELECT ?, ?, 'PRIMARY', 0
            WHERE NOT EXISTS (
                SELECT 1 FROM trainer_allocations
                WHERE programme_id = ? AND officer_id = ?
            )
        """, (programme_id, coordinator_id, programme_id, coordinator_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'UPDATE', 'training_programme', ?, ?, 'Coordinator allocated')
        """, (user['officer_id'], programme_id, f"coordinator={coordinator_id}"))

    return RedirectResponse(url="/approvals", status_code=302)


# Budget Approval Workflow
@router.post("/budget/{programme_id}/submit")
async def submit_training_budget(request: Request, programme_id: int):
    """Coordinator submits budget for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT coordinator_id FROM training_programmes WHERE id = ?", (programme_id,))
        programme = cursor.fetchone()
        if not programme or programme['coordinator_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/training?error=unauthorized", status_code=302)

        cursor.execute("""
            UPDATE training_programmes
            SET budget_approval_status = 'SUBMITTED',
                budget_submitted_by = ?,
                budget_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'training_budget', ?, 'Budget submitted for approval')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}?success=budget_submitted", status_code=302)


@router.post("/budget/{programme_id}/approve")
async def approve_training_budget(request: Request, programme_id: int):
    """Head approves training budget."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET budget_approval_status = 'APPROVED',
                budget_approved_by = ?,
                budget_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'training_budget', ?, 'Budget approved')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/budget/{programme_id}/reject")
async def reject_training_budget(
    request: Request,
    programme_id: int,
    rejection_remarks: str = Form(...)
):
    """Head rejects training budget."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET budget_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'training_budget', ?, ?)
        """, (user['officer_id'], programme_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# Trainer Allocation Approval Workflow
@router.post("/trainer/{programme_id}/submit")
async def submit_trainer_allocation(request: Request, programme_id: int):
    """Coordinator submits trainer allocation for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT coordinator_id FROM training_programmes WHERE id = ?", (programme_id,))
        programme = cursor.fetchone()
        if not programme or programme['coordinator_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/training?error=unauthorized", status_code=302)

        # Check trainers exist
        cursor.execute("SELECT COUNT(*) as cnt FROM trainer_allocations WHERE programme_id = ?", (programme_id,))
        if cursor.fetchone()['cnt'] == 0:
            return RedirectResponse(url=f"/training/trainers/{programme_id}?error=no_trainers", status_code=302)

        cursor.execute("""
            UPDATE training_programmes
            SET trainer_approval_status = 'SUBMITTED',
                trainer_submitted_by = ?,
                trainer_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'trainer_allocation', ?, 'Trainer allocation submitted for approval')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}?success=trainer_submitted", status_code=302)


@router.post("/trainer/{programme_id}/approve")
async def approve_trainer_allocation(request: Request, programme_id: int):
    """Head approves trainer allocation."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET trainer_approval_status = 'APPROVED',
                trainer_approved_by = ?,
                trainer_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'trainer_allocation', ?, 'Trainer allocation approved')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/trainer/{programme_id}/reject")
async def reject_trainer_allocation(
    request: Request,
    programme_id: int,
    rejection_remarks: str = Form(...)
):
    """Head rejects trainer allocation."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET trainer_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'trainer_allocation', ?, ?)
        """, (user['officer_id'], programme_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# Revenue Share Approval Workflow
@router.post("/revenue/{programme_id}/submit")
async def submit_training_revenue(request: Request, programme_id: int):
    """Coordinator submits revenue shares for Head approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT coordinator_id FROM training_programmes WHERE id = ?", (programme_id,))
        programme = cursor.fetchone()
        if not programme or programme['coordinator_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/training?error=unauthorized", status_code=302)

        # Check total allocation is 100%
        cursor.execute("""
            SELECT COALESCE(SUM(allocation_percent), 0) as total
            FROM trainer_allocations WHERE programme_id = ?
        """, (programme_id,))
        total = cursor.fetchone()['total'] or 0
        if abs(total - 100) > 0.01:
            return RedirectResponse(url=f"/training/trainers/{programme_id}?error=total_not_100", status_code=302)

        cursor.execute("""
            UPDATE training_programmes
            SET revenue_approval_status = 'SUBMITTED',
                revenue_submitted_by = ?,
                revenue_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'SUBMIT', 'training_revenue', ?, 'Revenue shares submitted for approval')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}?success=revenue_submitted", status_code=302)


@router.post("/revenue/{programme_id}/approve")
async def approve_training_revenue(request: Request, programme_id: int):
    """Head approves training revenue shares."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET revenue_approval_status = 'APPROVED',
                revenue_approved_by = ?,
                revenue_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'training_revenue', ?, 'Revenue shares approved')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url="/approvals", status_code=302)


@router.post("/revenue/{programme_id}/reject")
async def reject_training_revenue(
    request: Request,
    programme_id: int,
    rejection_remarks: str = Form(...)
):
    """Head rejects training revenue shares."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return RedirectResponse(url="/training?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE training_programmes
            SET revenue_approval_status = 'REJECTED',
                remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rejection_remarks, programme_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'training_revenue', ?, ?)
        """, (user['officer_id'], programme_id, rejection_remarks))

    return RedirectResponse(url="/approvals", status_code=302)


# Invoice Approval for Training
@router.post("/invoice/{programme_id}/request")
async def request_training_invoice(
    request: Request,
    programme_id: int,
    invoice_amount: float = Form(...),
    fy_period: str = Form(...)
):
    """Coordinator requests invoice for training programme."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM training_programmes WHERE id = ?", (programme_id,))
        programme = cursor.fetchone()
        if not programme:
            return RedirectResponse(url="/training", status_code=302)

        programme = dict(programme)

        # Generate invoice request number
        today = date.today()
        prefix = f"TRN-INV-{programme['office_id']}-{today.strftime('%Y%m')}"
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_num FROM invoice_requests
                WHERE request_number LIKE %s
            """, (f"{prefix}%",))
        else:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_num FROM invoice_requests
                WHERE request_number LIKE ?
            """, (f"{prefix}%",))
        next_num = cursor.fetchone()['next_num']
        request_number = f"{prefix}-{next_num:03d}"

        # Create invoice request (using NULL for assignment_id, linking via remarks)
        cursor.execute("""
            INSERT INTO invoice_requests
            (request_number, assignment_id, invoice_type, invoice_amount,
             fy_period, description, status, requested_by)
            VALUES (?, NULL, 'TRAINING', ?, ?, ?, 'PENDING', ?)
        """, (
            request_number,
            invoice_amount,
            fy_period,
            f"Training Programme: {programme['programme_number']} - {programme['title']}",
            user['officer_id']
        ))

        # Update programme
        cursor.execute("""
            UPDATE training_programmes
            SET invoice_raised = 1,
                invoice_date = CURRENT_DATE,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (programme_id,))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'CREATE', 'training_invoice', ?, 'Invoice request submitted')
        """, (user['officer_id'], programme_id))

    return RedirectResponse(url=f"/training/view/{programme_id}?success=invoice_requested", status_code=302)
