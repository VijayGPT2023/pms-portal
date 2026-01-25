"""
Admin routes for user management and system configuration.
"""
import secrets
import bcrypt
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.dependencies import get_current_user, is_admin
from app.roles import ROLE_NAMES, ALL_ROLES
from app.templates_config import templates

router = APIRouter()


def require_admin_access(request: Request):
    """Check if user is admin, return user or redirect."""
    user = get_current_user(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=302)
    if not is_admin(user):
        return None, RedirectResponse(url="/dashboard", status_code=302)
    return user, None


@router.get("/users", response_class=HTMLResponse)
async def user_management_page(request: Request, filter_office: str = None,
                                filter_role: str = None, search: str = None):
    """Display user management page. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        # Build query based on filters
        query = """
            SELECT officer_id, name, email, designation, office_id, admin_role_id, is_active
            FROM officers
            WHERE 1=1
        """
        params = []

        if filter_office:
            query += " AND office_id = ?"
            params.append(filter_office)

        if filter_role:
            if filter_role == 'OFFICER':
                query += " AND (admin_role_id IS NULL OR admin_role_id = '')"
            else:
                query += " AND admin_role_id = ?"
                params.append(filter_role)

        if search:
            query += " AND (name LIKE ? OR email LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY office_id, name"

        cursor.execute(query, params)
        all_officers = [dict(row) for row in cursor.fetchall()]

        # Get offices for filter
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "user": user,
        "officers": all_officers,
        "offices": offices,
        "roles": ROLE_NAMES,
        "filter_office": filter_office,
        "filter_role": filter_role,
        "search": search
    })


@router.post("/users/role")
async def update_user_role(request: Request, officer_id: str = Form(...), role: str = Form(None)):
    """Update a user's role. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        # Validate role
        if role and role not in ALL_ROLES:
            role = None

        cursor.execute("""
            UPDATE officers SET admin_role_id = ? WHERE officer_id = ?
        """, (role if role else None, officer_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'UPDATE', 'officer', ?, ?, ?)
        """, (user['officer_id'], 0, f"role={role}", f"Role changed for {officer_id}"))

    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/users/reset-password")
async def reset_user_password_route(request: Request, officer_id: str = Form(...)):
    """Reset a user's password. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    # Generate new password
    new_password = secrets.token_urlsafe(8)
    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    with get_db() as conn:
        cursor = conn.cursor()

        # Get officer name
        cursor.execute("SELECT name FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()

        if officer:
            cursor.execute("""
                UPDATE officers SET password_hash = ? WHERE officer_id = ?
            """, (password_hash, officer_id))

            # Log the action
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                VALUES (?, 'UPDATE', 'officer', ?, ?)
            """, (user['officer_id'], 0, f"Password reset for {officer_id}"))

            # Return to page with reset result
            cursor.execute("""
                SELECT officer_id, name, email, designation, office_id, admin_role_id, is_active
                FROM officers
                ORDER BY office_id, name
            """)
            all_officers = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
            offices = [dict(row) for row in cursor.fetchall()]

            return templates.TemplateResponse("admin_users.html", {
                "request": request,
                "user": user,
                "officers": all_officers,
                "offices": offices,
                "roles": ROLE_NAMES,
                "reset_result": {
                    "name": officer['name'],
                    "password": new_password
                }
            })

    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/roles", response_class=HTMLResponse)
async def roles_management_page(request: Request, show_history: bool = False):
    """Display role and hierarchy management page. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    from datetime import date
    today = date.today().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get all officers
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers WHERE is_active = 1
            ORDER BY name
        """)
        officers = [dict(row) for row in cursor.fetchall()]

        # Get all role assignments (including history if requested)
        if show_history:
            cursor.execute("""
                SELECT r.*, o.name as officer_name, o.office_id
                FROM officer_roles r
                JOIN officers o ON r.officer_id = o.officer_id
                ORDER BY r.effective_to IS NULL DESC, o.name, r.role_type
            """)
        else:
            cursor.execute("""
                SELECT r.*, o.name as officer_name, o.office_id
                FROM officer_roles r
                JOIN officers o ON r.officer_id = o.officer_id
                WHERE r.effective_to IS NULL
                ORDER BY o.name, r.role_type
            """)
        officer_roles = [dict(row) for row in cursor.fetchall()]

        # Get reporting hierarchy
        cursor.execute("""
            SELECT * FROM reporting_hierarchy
            WHERE effective_to IS NULL OR effective_to >= DATE('now')
            ORDER BY entity_type, entity_value
        """)
        hierarchy = [dict(row) for row in cursor.fetchall()]

        # Get groups
        cursor.execute("SELECT * FROM groups ORDER BY group_code")
        groups = [dict(row) for row in cursor.fetchall()]

        # Get offices
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices_list = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("admin_roles.html", {
        "request": request,
        "user": user,
        "officers": officers,
        "officer_roles": officer_roles,
        "hierarchy": hierarchy,
        "groups": groups,
        "offices": offices_list,
        "today": today,
        "show_history": show_history
    })


@router.post("/roles/assign")
async def assign_role(request: Request, officer_id: str = Form(...),
                      role_type: str = Form(...), scope_type: str = Form(None),
                      scope_value: str = Form(None), is_primary: int = Form(0),
                      effective_from: str = Form(None), order_reference: str = Form(None)):
    """Assign a role to an officer with effective date tracking. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    from datetime import date
    eff_date = effective_from or date.today().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        # End any existing active role of the same type for this scope
        # (e.g., if assigning new Group Head for HRM, end the previous one)
        if scope_value:
            cursor.execute("""
                UPDATE officer_roles
                SET effective_to = ?
                WHERE role_type = ? AND scope_value = ?
                AND effective_to IS NULL AND officer_id != ?
            """, (eff_date, role_type, scope_value, officer_id))

        # Check if this officer already has this exact role active
        cursor.execute("""
            SELECT id FROM officer_roles
            WHERE officer_id = ? AND role_type = ? AND scope_value IS ?
            AND effective_to IS NULL
        """, (officer_id, role_type, scope_value))
        existing = cursor.fetchone()

        if not existing:
            # Insert new role assignment
            cursor.execute("""
                INSERT INTO officer_roles
                (officer_id, role_type, scope_type, scope_value, is_primary, effective_from, order_reference, assigned_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (officer_id, role_type, scope_type or 'GLOBAL', scope_value, is_primary, eff_date, order_reference, user['officer_id']))

        # Also update legacy admin_role_id if this is primary
        if is_primary:
            cursor.execute("""
                UPDATE officers SET admin_role_id = ? WHERE officer_id = ?
            """, (role_type, officer_id))

        # Record in officer_history
        cursor.execute("""
            INSERT INTO officer_history
            (officer_id, change_type, field_name, new_value, effective_from, order_reference, remarks, changed_by)
            VALUES (?, 'ROLE_ASSIGN', 'role', ?, ?, ?, ?, ?)
        """, (officer_id, f"{role_type}:{scope_value or 'GLOBAL'}", eff_date, order_reference,
              f"Role {role_type} assigned", user['officer_id']))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'role', 0, ?, ?)
        """, (user['officer_id'], f"role={role_type},scope={scope_value},from={eff_date}", f"Role assigned to {officer_id}"))

    return RedirectResponse(url="/admin/roles", status_code=302)


@router.post("/roles/remove")
async def remove_role(request: Request, role_id: int = Form(...),
                      effective_to: str = Form(None), order_reference: str = Form(None),
                      remarks: str = Form(None)):
    """End a role assignment (set effective_to date). Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    from datetime import date
    end_date = effective_to or date.today().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get role info
        cursor.execute("""
            SELECT officer_id, role_type, scope_value, effective_from
            FROM officer_roles WHERE id = ?
        """, (role_id,))
        role = cursor.fetchone()

        if role:
            # Set effective_to instead of deleting (preserves history)
            cursor.execute("""
                UPDATE officer_roles SET effective_to = ? WHERE id = ?
            """, (end_date, role_id))

            # Record in officer_history
            history_remarks = remarks or f"Role {role['role_type']} ended"
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, old_value, effective_from, effective_to, order_reference, remarks, changed_by)
                VALUES (?, 'ROLE_REMOVE', 'role', ?, ?, ?, ?, ?, ?)
            """, (role['officer_id'], f"{role['role_type']}:{role['scope_value'] or 'GLOBAL'}",
                  role['effective_from'], end_date, order_reference, history_remarks, user['officer_id']))

            # Log the action
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, old_data, remarks)
                VALUES (?, 'UPDATE', 'role', ?, ?, ?)
            """, (user['officer_id'], role_id, f"role={role['role_type']}", f"Role ended for {role['officer_id']} on {end_date}"))

    return RedirectResponse(url="/admin/roles", status_code=302)


@router.post("/officer/transfer")
async def transfer_officer(request: Request, officer_id: str = Form(...),
                           to_office_id: str = Form(...), effective_from: str = Form(None),
                           transfer_order_no: str = Form(None), transfer_order_date: str = Form(None),
                           remarks: str = Form(None)):
    """Transfer an officer to a new office with history tracking. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    from datetime import date
    eff_date = effective_from or date.today().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get current office
        cursor.execute("SELECT office_id FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/admin/users", status_code=302)

        from_office = officer['office_id']

        # End previous transfer record if exists
        cursor.execute("""
            UPDATE office_transfer_history
            SET effective_to = ?
            WHERE officer_id = ? AND effective_to IS NULL
        """, (eff_date, officer_id))

        # Insert new transfer record
        cursor.execute("""
            INSERT INTO office_transfer_history
            (officer_id, from_office_id, to_office_id, effective_from, transfer_order_no, transfer_order_date, remarks, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (officer_id, from_office, to_office_id, eff_date, transfer_order_no, transfer_order_date, remarks, user['officer_id']))

        # Update officer's current office
        cursor.execute("""
            UPDATE officers SET office_id = ? WHERE officer_id = ?
        """, (to_office_id, officer_id))

        # Record in officer_history
        cursor.execute("""
            INSERT INTO officer_history
            (officer_id, change_type, field_name, old_value, new_value, effective_from, order_reference, remarks, changed_by)
            VALUES (?, 'OFFICE_TRANSFER', 'office_id', ?, ?, ?, ?, ?, ?)
        """, (officer_id, from_office, to_office_id, eff_date, transfer_order_no, remarks, user['officer_id']))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, old_data, new_data, remarks)
            VALUES (?, 'UPDATE', 'officer', 0, ?, ?, ?)
        """, (user['officer_id'], f"office={from_office}", f"office={to_office_id}", f"Officer {officer_id} transferred"))

    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/officer/promote")
async def promote_officer(request: Request, officer_id: str = Form(...),
                          new_designation: str = Form(...), effective_from: str = Form(None),
                          promotion_order_no: str = Form(None), promotion_order_date: str = Form(None),
                          pay_level: str = Form(None), remarks: str = Form(None)):
    """Promote an officer to a new designation with history tracking. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    from datetime import date
    eff_date = effective_from or date.today().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get current designation
        cursor.execute("SELECT designation FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/admin/users", status_code=302)

        old_designation = officer['designation']

        # End previous designation record if exists
        cursor.execute("""
            UPDATE designation_history
            SET effective_to = ?
            WHERE officer_id = ? AND effective_to IS NULL
        """, (eff_date, officer_id))

        # Insert new designation record
        cursor.execute("""
            INSERT INTO designation_history
            (officer_id, designation, pay_level, effective_from, promotion_order_no, promotion_order_date, remarks, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (officer_id, new_designation, pay_level, eff_date, promotion_order_no, promotion_order_date, remarks, user['officer_id']))

        # Update officer's current designation
        cursor.execute("""
            UPDATE officers SET designation = ? WHERE officer_id = ?
        """, (new_designation, officer_id))

        # Record in officer_history
        cursor.execute("""
            INSERT INTO officer_history
            (officer_id, change_type, field_name, old_value, new_value, effective_from, order_reference, remarks, changed_by)
            VALUES (?, 'DESIGNATION', 'designation', ?, ?, ?, ?, ?, ?)
        """, (officer_id, old_designation, new_designation, eff_date, promotion_order_no, remarks, user['officer_id']))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, old_data, new_data, remarks)
            VALUES (?, 'UPDATE', 'officer', 0, ?, ?, ?)
        """, (user['officer_id'], f"designation={old_designation}", f"designation={new_designation}", f"Officer {officer_id} promoted"))

    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/officer/{officer_id}/history", response_class=HTMLResponse)
async def officer_history(request: Request, officer_id: str):
    """View complete history of an officer's changes. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        # Get officer info
        cursor.execute("SELECT * FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/admin/users", status_code=302)
        officer = dict(officer)

        # Get role history
        cursor.execute("""
            SELECT * FROM officer_roles
            WHERE officer_id = ?
            ORDER BY effective_from DESC
        """, (officer_id,))
        role_history = [dict(row) for row in cursor.fetchall()]

        # Get designation history
        cursor.execute("""
            SELECT * FROM designation_history
            WHERE officer_id = ?
            ORDER BY effective_from DESC
        """, (officer_id,))
        designation_history = [dict(row) for row in cursor.fetchall()]

        # Get transfer history
        cursor.execute("""
            SELECT t.*, f.office_name as from_office_name, o.office_name as to_office_name
            FROM office_transfer_history t
            LEFT JOIN offices f ON t.from_office_id = f.office_id
            LEFT JOIN offices o ON t.to_office_id = o.office_id
            WHERE t.officer_id = ?
            ORDER BY t.effective_from DESC
        """, (officer_id,))
        transfer_history = [dict(row) for row in cursor.fetchall()]

        # Get general history
        cursor.execute("""
            SELECT * FROM officer_history
            WHERE officer_id = ?
            ORDER BY created_at DESC
        """, (officer_id,))
        general_history = [dict(row) for row in cursor.fetchall()]

        # Get offices for transfer form
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("officer_history.html", {
        "request": request,
        "user": user,
        "officer": officer,
        "role_history": role_history,
        "designation_history": designation_history,
        "transfer_history": transfer_history,
        "general_history": general_history,
        "offices": offices
    })


@router.post("/hierarchy/add")
async def add_hierarchy(request: Request, entity_type: str = Form(...),
                        entity_value: str = Form(...), reports_to: str = Form(...)):
    """Add a reporting hierarchy entry. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO reporting_hierarchy
            (entity_type, entity_value, reports_to_role, updated_by)
            VALUES (?, ?, ?, ?)
        """, (entity_type, entity_value.upper(), reports_to, user['officer_id']))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'hierarchy', 0, ?, ?)
        """, (user['officer_id'], f"{entity_type}:{entity_value} -> {reports_to}", "Hierarchy entry added"))

    return RedirectResponse(url="/admin/roles", status_code=302)


@router.post("/hierarchy/change")
async def change_hierarchy(request: Request, entity_type: str = Form(...),
                           entity_value: str = Form(...), reports_to: str = Form(...)):
    """Change reporting hierarchy. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE reporting_hierarchy
            SET reports_to_role = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE entity_type = ? AND entity_value = ?
        """, (reports_to, user['officer_id'], entity_type, entity_value))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'UPDATE', 'hierarchy', 0, ?, ?)
        """, (user['officer_id'], f"{entity_type}:{entity_value} -> {reports_to}", "Hierarchy changed"))

    return RedirectResponse(url="/admin/roles", status_code=302)


@router.post("/groups/add")
async def add_group(request: Request, group_code: str = Form(...),
                    group_name: str = Form(...), description: str = Form(None)):
    """Add a new group. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO groups (group_code, group_name, description)
            VALUES (?, ?, ?)
        """, (group_code.upper(), group_name, description))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'group', 0, ?, ?)
        """, (user['officer_id'], f"code={group_code}", "Group added"))

    return RedirectResponse(url="/admin/roles", status_code=302)


@router.get("/activity-log", response_class=HTMLResponse)
async def activity_log_page(request: Request, action: str = None, entity_type: str = None,
                            from_date: str = None, to_date: str = None, actor_id: str = None,
                            page: int = 1):
    """View activity log. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    per_page = 50

    with get_db() as conn:
        cursor = conn.cursor()

        # Build query with filters
        query = """
            SELECT l.*, o.name as actor_name
            FROM activity_log l
            LEFT JOIN officers o ON l.actor_id = o.officer_id
            WHERE 1=1
        """
        count_query = "SELECT COUNT(*) FROM activity_log l WHERE 1=1"
        params = []

        if action:
            query += " AND l.action = ?"
            count_query += " AND l.action = ?"
            params.append(action)

        if entity_type:
            query += " AND l.entity_type = ?"
            count_query += " AND l.entity_type = ?"
            params.append(entity_type)

        if from_date:
            query += " AND DATE(l.created_at) >= ?"
            count_query += " AND DATE(l.created_at) >= ?"
            params.append(from_date)

        if to_date:
            query += " AND DATE(l.created_at) <= ?"
            count_query += " AND DATE(l.created_at) <= ?"
            params.append(to_date)

        if actor_id:
            query += " AND l.actor_id = ?"
            count_query += " AND l.actor_id = ?"
            params.append(actor_id)

        # Get total count
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]
        total_pages = (total_count + per_page - 1) // per_page

        # Get paginated results
        query += " ORDER BY l.created_at DESC LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])

        cursor.execute(query, params)
        activities = [dict(row) for row in cursor.fetchall()]

        # Get all officers for filter dropdown
        cursor.execute("SELECT officer_id, name FROM officers ORDER BY name")
        officers = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("activity_log.html", {
        "request": request,
        "user": user,
        "activities": activities,
        "officers": officers,
        "filter_action": action,
        "filter_entity": entity_type,
        "filter_from_date": from_date,
        "filter_to_date": to_date,
        "filter_actor": actor_id,
        "page": page,
        "total_pages": total_pages
    })
