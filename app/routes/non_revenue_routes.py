"""
Routes for Non-Revenue Activity Management.
Workflow: Suggestion → Proposal Request → Proposal → Execution

Non-Revenue activities include: Capacity Building, Knowledge Sharing, Internal Projects, Research, etc.
"""
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import date, datetime

from app.database import get_db, generate_suggestion_number, USE_POSTGRES
from app.dependencies import get_current_user
from app.templates_config import templates

router = APIRouter(prefix="/non-revenue", tags=["non-revenue"])

# Parameter placeholder based on database type
PH = '%s' if USE_POSTGRES else '?'


def is_office_head(user, office_id):
    """Check if user is Head of the given office."""
    admin_role = (user.get('admin_role_id', '') or '').upper()
    head_roles = ['ADMIN', 'DG', 'DDG', 'DDG-I', 'DDG-II', 'RD_HEAD', 'GROUP_HEAD', 'HEAD', 'TEAM_LEADER']
    if admin_role in head_roles:
        return True

    date_func = 'CURRENT_DATE' if USE_POSTGRES else "DATE('now')"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT 1 FROM officer_roles
            WHERE officer_id = {PH}
            AND role_type IN ('DG', 'DDG-I', 'DDG-II', 'RD_HEAD', 'GROUP_HEAD')
            AND (effective_to IS NULL OR effective_to >= {date_func})
        """, (user['officer_id'],))
        if cursor.fetchone():
            return True

        if user.get('office_id') == office_id:
            cursor.execute(f"""
                SELECT 1 FROM officer_roles
                WHERE officer_id = {PH}
                AND role_type IN ('RD_HEAD', 'GROUP_HEAD', 'TEAM_LEADER')
                AND (effective_to IS NULL OR effective_to >= {date_func})
            """, (user['officer_id'],))
            if cursor.fetchone():
                return True
    return False


@router.get("/", response_class=HTMLResponse)
async def list_suggestions(request: Request, status: str = None, office: str = None, view: str = None):
    """List all non-revenue suggestions with filters."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        conditions = ["1=1"]
        params = []

        if status:
            conditions.append(f"s.status = {PH}")
            params.append(status)

        if office:
            conditions.append(f"s.office_id = {PH}")
            params.append(office)

        admin_role = user.get('admin_role_id', '')
        if view == 'pending_approval' and admin_role in ['ADMIN', 'DG', 'DDG', 'HEAD']:
            conditions.append("s.approval_status = 'PENDING'")
        elif view == 'my_created':
            conditions.append(f"s.created_by = {PH}")
            params.append(user['officer_id'])
        elif view == 'my_allocated':
            conditions.append(f"s.officer_id = {PH}")
            params.append(user['officer_id'])
        elif admin_role not in ['ADMIN', 'DG', 'DDG']:
            conditions.append(f"s.office_id = {PH}")
            params.append(user['office_id'])

        where_clause = " AND ".join(conditions)
        cursor.execute(f"""
            SELECT s.*, o.name as officer_name, off.office_name,
                   creator.name as created_by_name, approver.name as approved_by_name
            FROM non_revenue_suggestions s
            LEFT JOIN officers o ON s.officer_id = o.officer_id
            LEFT JOIN offices off ON s.office_id = off.office_id
            LEFT JOIN officers creator ON s.created_by = creator.officer_id
            LEFT JOIN officers approver ON s.approved_by = approver.officer_id
            WHERE {where_clause}
            ORDER BY s.created_at DESC
        """, params)
        suggestions = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT status, COUNT(*) as count FROM non_revenue_suggestions GROUP BY status")
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) as count FROM non_revenue_suggestions WHERE approval_status = 'PENDING'")
        pending_approval_count = cursor.fetchone()['count']

    is_head = is_office_head(user, user.get('office_id'))

    return templates.TemplateResponse("non_revenue_list.html", {
        "request": request,
        "user": user,
        "suggestions": suggestions,
        "offices": offices,
        "status_counts": status_counts,
        "pending_approval_count": pending_approval_count,
        "filter_status": status,
        "filter_office": office,
        "filter_view": view,
        "is_head": is_head,
    })


@router.get("/create", response_class=HTMLResponse)
async def create_suggestion_form(request: Request):
    """Show form to create new non-revenue suggestion."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = [dict(row) for row in cursor.fetchall()]

    activity_types = [
        {'value': 'CAPACITY_BUILDING', 'label': 'Capacity Building'},
        {'value': 'KNOWLEDGE_SHARING', 'label': 'Knowledge Sharing'},
        {'value': 'INTERNAL_PROJECT', 'label': 'Internal Project'},
        {'value': 'RESEARCH', 'label': 'Research & Development'},
        {'value': 'DOCUMENTATION', 'label': 'Documentation'},
        {'value': 'PROCESS_IMPROVEMENT', 'label': 'Process Improvement'},
        {'value': 'OTHER', 'label': 'Other'},
    ]

    return templates.TemplateResponse("non_revenue_form.html", {
        "request": request,
        "user": user,
        "offices": offices,
        "activity_types": activity_types,
        "suggestion": None,
        "is_new": True,
    })


@router.post("/create", response_class=HTMLResponse)
async def create_suggestion(
    request: Request,
    title: str = Form(...),
    activity_type: str = Form(...),
    office_id: str = Form(...),
    description: str = Form(None),
    beneficiary: str = Form(None),
    justification: str = Form(None),
    expected_outcome: str = Form(None),
    notional_value: float = Form(0),
    target_start_date: str = Form(None),
    target_end_date: str = Form(None),
    remarks: str = Form(None),
):
    """Create new non-revenue suggestion."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    suggestion_number = generate_suggestion_number(office_id)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            INSERT INTO non_revenue_suggestions (
                suggestion_number, title, description, activity_type, beneficiary,
                domain, office_id, justification, expected_outcome, notional_value,
                target_start_date, target_end_date, status, approval_status,
                remarks, created_by, created_at
            ) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        """, (
            suggestion_number, title, description, activity_type, beneficiary,
            None, office_id, justification, expected_outcome, notional_value,
            target_start_date or None, target_end_date or None,
            'PENDING_APPROVAL', 'PENDING',
            remarks, user['officer_id'], datetime.now()
        ))
        conn.commit()

    return RedirectResponse(url="/non-revenue/?view=my_created", status_code=302)


@router.get("/view/{suggestion_id}", response_class=HTMLResponse)
async def view_suggestion(request: Request, suggestion_id: int):
    """View non-revenue suggestion details."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT s.*, o.name as officer_name, off.office_name,
                   creator.name as created_by_name, approver.name as approved_by_name
            FROM non_revenue_suggestions s
            LEFT JOIN officers o ON s.officer_id = o.officer_id
            LEFT JOIN offices off ON s.office_id = off.office_id
            LEFT JOIN officers creator ON s.created_by = creator.officer_id
            LEFT JOIN officers approver ON s.approved_by = approver.officer_id
            WHERE s.id = {PH}
        """, (suggestion_id,))
        suggestion = cursor.fetchone()

        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        suggestion = dict(suggestion)

        # Get officers for allocation dropdown
        cursor.execute(f"""
            SELECT officer_id, name, office_id FROM officers
            WHERE office_id = {PH} OR {PH} IN ('ADMIN', 'DG', 'DDG')
            ORDER BY name
        """, (suggestion['office_id'], user.get('admin_role_id', '')))
        officers = [dict(row) for row in cursor.fetchall()]

    is_head = is_office_head(user, suggestion['office_id'])
    can_edit = (suggestion.get('created_by') == user['officer_id'] and suggestion.get('approval_status') == 'PENDING') or is_head

    activity_types = {
        'CAPACITY_BUILDING': 'Capacity Building',
        'KNOWLEDGE_SHARING': 'Knowledge Sharing',
        'INTERNAL_PROJECT': 'Internal Project',
        'RESEARCH': 'Research & Development',
        'DOCUMENTATION': 'Documentation',
        'PROCESS_IMPROVEMENT': 'Process Improvement',
        'OTHER': 'Other',
    }

    return templates.TemplateResponse("non_revenue_view.html", {
        "request": request,
        "user": user,
        "suggestion": suggestion,
        "officers": officers,
        "is_head": is_head,
        "can_edit": can_edit,
        "activity_types": activity_types,
    })


@router.post("/approve/{suggestion_id}", response_class=HTMLResponse)
async def approve_suggestion(
    request: Request,
    suggestion_id: int,
    officer_id: str = Form(None),
):
    """Approve non-revenue suggestion and optionally allocate officer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM non_revenue_suggestions WHERE id = {PH}", (suggestion_id,))
        suggestion = cursor.fetchone()
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        if not is_office_head(user, dict(suggestion)['office_id']):
            raise HTTPException(status_code=403, detail="Not authorized")

        cursor.execute(f"""
            UPDATE non_revenue_suggestions
            SET approval_status = 'APPROVED',
                status = 'IN_PROGRESS',
                approved_by = {PH},
                approved_at = {PH},
                officer_id = {PH},
                updated_at = {PH}
            WHERE id = {PH}
        """, (user['officer_id'], datetime.now(), officer_id, datetime.now(), suggestion_id))
        conn.commit()

    return RedirectResponse(url=f"/non-revenue/view/{suggestion_id}", status_code=302)


@router.post("/reject/{suggestion_id}", response_class=HTMLResponse)
async def reject_suggestion(
    request: Request,
    suggestion_id: int,
    rejection_reason: str = Form(...),
):
    """Reject non-revenue suggestion."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM non_revenue_suggestions WHERE id = {PH}", (suggestion_id,))
        suggestion = cursor.fetchone()
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        if not is_office_head(user, dict(suggestion)['office_id']):
            raise HTTPException(status_code=403, detail="Not authorized")

        cursor.execute(f"""
            UPDATE non_revenue_suggestions
            SET approval_status = 'REJECTED',
                status = 'REJECTED',
                rejection_reason = {PH},
                approved_by = {PH},
                approved_at = {PH},
                updated_at = {PH}
            WHERE id = {PH}
        """, (rejection_reason, user['officer_id'], datetime.now(), datetime.now(), suggestion_id))
        conn.commit()

    return RedirectResponse(url="/non-revenue/?view=pending_approval", status_code=302)


@router.post("/update/{suggestion_id}", response_class=HTMLResponse)
async def update_suggestion_progress(
    request: Request,
    suggestion_id: int,
    current_update: str = Form(...),
    status: str = Form(None),
):
    """Update progress on non-revenue suggestion."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM non_revenue_suggestions WHERE id = {PH}", (suggestion_id,))
        suggestion = cursor.fetchone()
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = dict(suggestion)
        if suggestion.get('officer_id') != user['officer_id'] and not is_office_head(user, suggestion['office_id']):
            raise HTTPException(status_code=403, detail="Not authorized")

        update_fields = [f"current_update = {PH}", f"updated_at = {PH}"]
        params = [current_update, datetime.now()]

        if status:
            update_fields.append(f"status = {PH}")
            params.append(status)

        params.append(suggestion_id)
        cursor.execute(f"""
            UPDATE non_revenue_suggestions
            SET {', '.join(update_fields)}
            WHERE id = {PH}
        """, params)
        conn.commit()

    return RedirectResponse(url=f"/non-revenue/view/{suggestion_id}", status_code=302)


@router.post("/complete/{suggestion_id}", response_class=HTMLResponse)
async def complete_suggestion(request: Request, suggestion_id: int):
    """Mark non-revenue suggestion as completed."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM non_revenue_suggestions WHERE id = {PH}", (suggestion_id,))
        suggestion = cursor.fetchone()
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = dict(suggestion)
        if suggestion.get('officer_id') != user['officer_id'] and not is_office_head(user, suggestion['office_id']):
            raise HTTPException(status_code=403, detail="Not authorized")

        cursor.execute(f"""
            UPDATE non_revenue_suggestions
            SET status = 'COMPLETED', updated_at = {PH}
            WHERE id = {PH}
        """, (datetime.now(), suggestion_id))
        conn.commit()

    return RedirectResponse(url=f"/non-revenue/view/{suggestion_id}", status_code=302)
