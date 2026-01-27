"""
Admin routes for user management and system configuration.
"""
import secrets
import bcrypt
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user, is_admin
from app.roles import ROLE_NAMES, ALL_ROLES
from app.templates_config import templates

router = APIRouter()


def ph(index=1):
    """Return placeholder for SQL query based on database type."""
    return '%s' if USE_POSTGRES else '?'


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
            query += f" AND office_id = {ph()}"
            params.append(filter_office)

        if filter_role:
            if filter_role == 'OFFICER':
                query += " AND (admin_role_id IS NULL OR admin_role_id = '')"
            else:
                query += f" AND admin_role_id = {ph()}"
                params.append(filter_role)

        if search:
            query += f" AND (name LIKE {ph()} OR email LIKE {ph()})"
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

        if USE_POSTGRES:
            cursor.execute(
                "UPDATE officers SET admin_role_id = %s WHERE officer_id = %s",
                (role if role else None, officer_id)
            )
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
                VALUES (%s, 'UPDATE', 'officer', %s, %s, %s)
            """, (user['officer_id'], 0, f"role={role}", f"Role changed for {officer_id}"))
        else:
            cursor.execute(
                "UPDATE officers SET admin_role_id = ? WHERE officer_id = ?",
                (role if role else None, officer_id)
            )
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
        if USE_POSTGRES:
            cursor.execute("SELECT name FROM officers WHERE officer_id = %s", (officer_id,))
        else:
            cursor.execute("SELECT name FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()

        if officer:
            if USE_POSTGRES:
                cursor.execute(
                    "UPDATE officers SET password_hash = %s WHERE officer_id = %s",
                    (password_hash, officer_id)
                )
                cursor.execute("""
                    INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
                    VALUES (%s, 'UPDATE', 'officer', %s, %s)
                """, (user['officer_id'], 0, f"Password reset for {officer_id}"))
            else:
                cursor.execute(
                    "UPDATE officers SET password_hash = ? WHERE officer_id = ?",
                    (password_hash, officer_id)
                )
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
            WHERE effective_to IS NULL OR effective_to >= CURRENT_DATE
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
        if scope_value:
            if USE_POSTGRES:
                cursor.execute("""
                    UPDATE officer_roles
                    SET effective_to = %s
                    WHERE role_type = %s AND scope_value = %s
                    AND effective_to IS NULL AND officer_id != %s
                """, (eff_date, role_type, scope_value, officer_id))
            else:
                cursor.execute("""
                    UPDATE officer_roles
                    SET effective_to = ?
                    WHERE role_type = ? AND scope_value = ?
                    AND effective_to IS NULL AND officer_id != ?
                """, (eff_date, role_type, scope_value, officer_id))

        # Check if this officer already has this exact role active
        if USE_POSTGRES:
            if scope_value:
                cursor.execute("""
                    SELECT id FROM officer_roles
                    WHERE officer_id = %s AND role_type = %s AND scope_value = %s
                    AND effective_to IS NULL
                """, (officer_id, role_type, scope_value))
            else:
                cursor.execute("""
                    SELECT id FROM officer_roles
                    WHERE officer_id = %s AND role_type = %s AND scope_value IS NULL
                    AND effective_to IS NULL
                """, (officer_id, role_type))
        else:
            cursor.execute("""
                SELECT id FROM officer_roles
                WHERE officer_id = ? AND role_type = ? AND scope_value IS ?
                AND effective_to IS NULL
            """, (officer_id, role_type, scope_value))
        existing = cursor.fetchone()

        if not existing:
            # Insert new role assignment
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, effective_from, order_reference, assigned_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (officer_id, role_type, scope_type or 'GLOBAL', scope_value, is_primary, eff_date, order_reference, user['officer_id']))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, effective_from, order_reference, assigned_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (officer_id, role_type, scope_type or 'GLOBAL', scope_value, is_primary, eff_date, order_reference, user['officer_id']))

        # Also update legacy admin_role_id if this is primary
        if is_primary:
            if USE_POSTGRES:
                cursor.execute(
                    "UPDATE officers SET admin_role_id = %s WHERE officer_id = %s",
                    (role_type, officer_id)
                )
            else:
                cursor.execute(
                    "UPDATE officers SET admin_role_id = ? WHERE officer_id = ?",
                    (role_type, officer_id)
                )

        # Record in officer_history
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, new_value, effective_from, order_reference, remarks, changed_by)
                VALUES (%s, 'ROLE_ASSIGN', 'role', %s, %s, %s, %s, %s)
            """, (officer_id, f"{role_type}:{scope_value or 'GLOBAL'}", eff_date, order_reference,
                  f"Role {role_type} assigned", user['officer_id']))
        else:
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, new_value, effective_from, order_reference, remarks, changed_by)
                VALUES (?, 'ROLE_ASSIGN', 'role', ?, ?, ?, ?, ?)
            """, (officer_id, f"{role_type}:{scope_value or 'GLOBAL'}", eff_date, order_reference,
                  f"Role {role_type} assigned", user['officer_id']))

        # Log the action
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
                VALUES (%s, 'CREATE', 'role', 0, %s, %s)
            """, (user['officer_id'], f"role={role_type},scope={scope_value},from={eff_date}", f"Role assigned to {officer_id}"))
        else:
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
        if USE_POSTGRES:
            cursor.execute("""
                SELECT officer_id, role_type, scope_value, effective_from
                FROM officer_roles WHERE id = %s
            """, (role_id,))
        else:
            cursor.execute("""
                SELECT officer_id, role_type, scope_value, effective_from
                FROM officer_roles WHERE id = ?
            """, (role_id,))
        role = cursor.fetchone()

        if role:
            # Set effective_to instead of deleting (preserves history)
            if USE_POSTGRES:
                cursor.execute(
                    "UPDATE officer_roles SET effective_to = %s WHERE id = %s",
                    (end_date, role_id)
                )
            else:
                cursor.execute(
                    "UPDATE officer_roles SET effective_to = ? WHERE id = ?",
                    (end_date, role_id)
                )

            # Record in officer_history
            history_remarks = remarks or f"Role {role['role_type']} ended"
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_history
                    (officer_id, change_type, field_name, old_value, effective_from, effective_to, order_reference, remarks, changed_by)
                    VALUES (%s, 'ROLE_REMOVE', 'role', %s, %s, %s, %s, %s, %s)
                """, (role['officer_id'], f"{role['role_type']}:{role['scope_value'] or 'GLOBAL'}",
                      role['effective_from'], end_date, order_reference, history_remarks, user['officer_id']))
            else:
                cursor.execute("""
                    INSERT INTO officer_history
                    (officer_id, change_type, field_name, old_value, effective_from, effective_to, order_reference, remarks, changed_by)
                    VALUES (?, 'ROLE_REMOVE', 'role', ?, ?, ?, ?, ?, ?)
                """, (role['officer_id'], f"{role['role_type']}:{role['scope_value'] or 'GLOBAL'}",
                      role['effective_from'], end_date, order_reference, history_remarks, user['officer_id']))

            # Log the action
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO activity_log (actor_id, action, entity_type, entity_id, old_data, remarks)
                    VALUES (%s, 'UPDATE', 'role', %s, %s, %s)
                """, (user['officer_id'], role_id, f"role={role['role_type']}", f"Role ended for {role['officer_id']} on {end_date}"))
            else:
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
        if USE_POSTGRES:
            cursor.execute("SELECT office_id FROM officers WHERE officer_id = %s", (officer_id,))
        else:
            cursor.execute("SELECT office_id FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/admin/users", status_code=302)

        from_office = officer['office_id']

        # End previous transfer record if exists
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE office_transfer_history
                SET effective_to = %s
                WHERE officer_id = %s AND effective_to IS NULL
            """, (eff_date, officer_id))
        else:
            cursor.execute("""
                UPDATE office_transfer_history
                SET effective_to = ?
                WHERE officer_id = ? AND effective_to IS NULL
            """, (eff_date, officer_id))

        # Insert new transfer record
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO office_transfer_history
                (officer_id, from_office_id, to_office_id, effective_from, transfer_order_no, transfer_order_date, remarks, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (officer_id, from_office, to_office_id, eff_date, transfer_order_no, transfer_order_date, remarks, user['officer_id']))
        else:
            cursor.execute("""
                INSERT INTO office_transfer_history
                (officer_id, from_office_id, to_office_id, effective_from, transfer_order_no, transfer_order_date, remarks, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (officer_id, from_office, to_office_id, eff_date, transfer_order_no, transfer_order_date, remarks, user['officer_id']))

        # Update officer's current office
        if USE_POSTGRES:
            cursor.execute(
                "UPDATE officers SET office_id = %s WHERE officer_id = %s",
                (to_office_id, officer_id)
            )
        else:
            cursor.execute(
                "UPDATE officers SET office_id = ? WHERE officer_id = ?",
                (to_office_id, officer_id)
            )

        # Record in officer_history
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, old_value, new_value, effective_from, order_reference, remarks, changed_by)
                VALUES (%s, 'OFFICE_TRANSFER', 'office_id', %s, %s, %s, %s, %s, %s)
            """, (officer_id, from_office, to_office_id, eff_date, transfer_order_no, remarks, user['officer_id']))
        else:
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, old_value, new_value, effective_from, order_reference, remarks, changed_by)
                VALUES (?, 'OFFICE_TRANSFER', 'office_id', ?, ?, ?, ?, ?, ?)
            """, (officer_id, from_office, to_office_id, eff_date, transfer_order_no, remarks, user['officer_id']))

        # Log the action
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, old_data, new_data, remarks)
                VALUES (%s, 'UPDATE', 'officer', 0, %s, %s, %s)
            """, (user['officer_id'], f"office={from_office}", f"office={to_office_id}", f"Officer {officer_id} transferred"))
        else:
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
        if USE_POSTGRES:
            cursor.execute("SELECT designation FROM officers WHERE officer_id = %s", (officer_id,))
        else:
            cursor.execute("SELECT designation FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/admin/users", status_code=302)

        old_designation = officer['designation']

        # End previous designation record if exists
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE designation_history
                SET effective_to = %s
                WHERE officer_id = %s AND effective_to IS NULL
            """, (eff_date, officer_id))
        else:
            cursor.execute("""
                UPDATE designation_history
                SET effective_to = ?
                WHERE officer_id = ? AND effective_to IS NULL
            """, (eff_date, officer_id))

        # Insert new designation record
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO designation_history
                (officer_id, designation, pay_level, effective_from, promotion_order_no, promotion_order_date, remarks, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (officer_id, new_designation, pay_level, eff_date, promotion_order_no, promotion_order_date, remarks, user['officer_id']))
        else:
            cursor.execute("""
                INSERT INTO designation_history
                (officer_id, designation, pay_level, effective_from, promotion_order_no, promotion_order_date, remarks, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (officer_id, new_designation, pay_level, eff_date, promotion_order_no, promotion_order_date, remarks, user['officer_id']))

        # Update officer's current designation
        if USE_POSTGRES:
            cursor.execute(
                "UPDATE officers SET designation = %s WHERE officer_id = %s",
                (new_designation, officer_id)
            )
        else:
            cursor.execute(
                "UPDATE officers SET designation = ? WHERE officer_id = ?",
                (new_designation, officer_id)
            )

        # Record in officer_history
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, old_value, new_value, effective_from, order_reference, remarks, changed_by)
                VALUES (%s, 'DESIGNATION', 'designation', %s, %s, %s, %s, %s, %s)
            """, (officer_id, old_designation, new_designation, eff_date, promotion_order_no, remarks, user['officer_id']))
        else:
            cursor.execute("""
                INSERT INTO officer_history
                (officer_id, change_type, field_name, old_value, new_value, effective_from, order_reference, remarks, changed_by)
                VALUES (?, 'DESIGNATION', 'designation', ?, ?, ?, ?, ?, ?)
            """, (officer_id, old_designation, new_designation, eff_date, promotion_order_no, remarks, user['officer_id']))

        # Log the action
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, old_data, new_data, remarks)
                VALUES (%s, 'UPDATE', 'officer', 0, %s, %s, %s)
            """, (user['officer_id'], f"designation={old_designation}", f"designation={new_designation}", f"Officer {officer_id} promoted"))
        else:
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
        if USE_POSTGRES:
            cursor.execute("SELECT * FROM officers WHERE officer_id = %s", (officer_id,))
        else:
            cursor.execute("SELECT * FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/admin/users", status_code=302)
        officer = dict(officer)

        # Get role history
        if USE_POSTGRES:
            cursor.execute("""
                SELECT * FROM officer_roles
                WHERE officer_id = %s
                ORDER BY effective_from DESC
            """, (officer_id,))
        else:
            cursor.execute("""
                SELECT * FROM officer_roles
                WHERE officer_id = ?
                ORDER BY effective_from DESC
            """, (officer_id,))
        role_history = [dict(row) for row in cursor.fetchall()]

        # Get designation history
        if USE_POSTGRES:
            cursor.execute("""
                SELECT * FROM designation_history
                WHERE officer_id = %s
                ORDER BY effective_from DESC
            """, (officer_id,))
        else:
            cursor.execute("""
                SELECT * FROM designation_history
                WHERE officer_id = ?
                ORDER BY effective_from DESC
            """, (officer_id,))
        designation_history = [dict(row) for row in cursor.fetchall()]

        # Get transfer history
        if USE_POSTGRES:
            cursor.execute("""
                SELECT t.*, f.office_name as from_office_name, o.office_name as to_office_name
                FROM office_transfer_history t
                LEFT JOIN offices f ON t.from_office_id = f.office_id
                LEFT JOIN offices o ON t.to_office_id = o.office_id
                WHERE t.officer_id = %s
                ORDER BY t.effective_from DESC
            """, (officer_id,))
        else:
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
        if USE_POSTGRES:
            cursor.execute("""
                SELECT * FROM officer_history
                WHERE officer_id = %s
                ORDER BY created_at DESC
            """, (officer_id,))
        else:
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

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role, updated_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (entity_type, entity_value) DO UPDATE SET
                reports_to_role = EXCLUDED.reports_to_role, updated_by = EXCLUDED.updated_by
            """, (entity_type, entity_value.upper(), reports_to, user['officer_id']))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO reporting_hierarchy
                (entity_type, entity_value, reports_to_role, updated_by)
                VALUES (?, ?, ?, ?)
            """, (entity_type, entity_value.upper(), reports_to, user['officer_id']))

        # Log the action
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
                VALUES (%s, 'CREATE', 'hierarchy', 0, %s, %s)
            """, (user['officer_id'], f"{entity_type}:{entity_value} -> {reports_to}", "Hierarchy entry added"))
        else:
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

        if USE_POSTGRES:
            cursor.execute("""
                UPDATE reporting_hierarchy
                SET reports_to_role = %s, updated_by = %s, updated_at = CURRENT_TIMESTAMP
                WHERE entity_type = %s AND entity_value = %s
            """, (reports_to, user['officer_id'], entity_type, entity_value))
        else:
            cursor.execute("""
                UPDATE reporting_hierarchy
                SET reports_to_role = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE entity_type = ? AND entity_value = ?
            """, (reports_to, user['officer_id'], entity_type, entity_value))

        # Log the action
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
                VALUES (%s, 'UPDATE', 'hierarchy', 0, %s, %s)
            """, (user['officer_id'], f"{entity_type}:{entity_value} -> {reports_to}", "Hierarchy changed"))
        else:
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

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO groups (group_code, group_name, description)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (group_code.upper(), group_name, description))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO groups (group_code, group_name, description)
                VALUES (?, ?, ?)
            """, (group_code.upper(), group_name, description))

        # Log the action
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
                VALUES (%s, 'CREATE', 'group', 0, %s, %s)
            """, (user['officer_id'], f"code={group_code}", "Group added"))
        else:
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

        # Build query with filters - handle placeholders dynamically
        base_query = """
            SELECT l.*, o.name as actor_name
            FROM activity_log l
            LEFT JOIN officers o ON l.actor_id = o.officer_id
            WHERE 1=1
        """
        count_base = "SELECT COUNT(*) FROM activity_log l WHERE 1=1"
        params = []
        conditions = []

        if action:
            conditions.append(f"l.action = {ph()}")
            params.append(action)

        if entity_type:
            conditions.append(f"l.entity_type = {ph()}")
            params.append(entity_type)

        if from_date:
            conditions.append(f"DATE(l.created_at) >= {ph()}")
            params.append(from_date)

        if to_date:
            conditions.append(f"DATE(l.created_at) <= {ph()}")
            params.append(to_date)

        if actor_id:
            conditions.append(f"l.actor_id = {ph()}")
            params.append(actor_id)

        if conditions:
            condition_str = " AND " + " AND ".join(conditions)
            base_query += condition_str
            count_base += condition_str

        # Get total count
        cursor.execute(count_base, params)
        total_count = cursor.fetchone()[0]
        total_pages = (total_count + per_page - 1) // per_page

        # Get paginated results
        base_query += f" ORDER BY l.created_at DESC LIMIT {ph()} OFFSET {ph()}"
        params.extend([per_page, (page - 1) * per_page])

        cursor.execute(base_query, params)
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


@router.get("/setup-roles", response_class=HTMLResponse)
async def setup_roles_page(request: Request):
    """Run initial role setup. Admin only."""
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    results = []
    ph = '%s' if USE_POSTGRES else '?'

    with get_db() as conn:
        cursor = conn.cursor()

        # STEP 1: Show all existing offices
        results.append("=== STEP 1: Existing Offices in Database ===")
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]
        for off in offices:
            results.append(f"  {off['office_id']}: {off['office_name']}")

        if not offices:
            results.append("  (No offices found - please import officers first)")

        # Build office_id mapping - map common patterns to DDG
        # DDG-I: Regional offices in South/West + IE, AB, ES, IT, Admin groups
        # DDG-II: Regional offices in North/East + ECA, EM, IS, Finance, HRM groups
        ddg1_patterns = ['CHN', 'Chennai', 'HYD', 'Hyderabad', 'BLR', 'Bengaluru', 'Bangalore',
                         'GNR', 'Gandhinagar', 'MUM', 'Mumbai', 'JAI', 'Jaipur',
                         'IE', 'AB', 'ES', 'IT', 'Admin']
        ddg2_patterns = ['CHD', 'Chandigarh', 'KNP', 'Kanpur', 'GUW', 'Guwahati',
                         'PAT', 'Patna', 'KOL', 'Kolkata', 'BBS', 'Bhubaneswar', 'Bhubneswar',
                         'ECA', 'EM', 'IS', 'Finance', 'HRM']

        ddg1_offices = []
        ddg2_offices = []
        for off in offices:
            oid = off['office_id']
            oname = off['office_name'] or ''
            # Check if matches DDG-I patterns
            if any(p.lower() in oid.lower() or p.lower() in oname.lower() for p in ddg1_patterns):
                ddg1_offices.append(oid)
            # Check if matches DDG-II patterns
            elif any(p.lower() in oid.lower() or p.lower() in oname.lower() for p in ddg2_patterns):
                ddg2_offices.append(oid)
            # HQ and NPC offices don't report to DDG

        results.append("")
        results.append("=== STEP 2: Office to DDG Mapping ===")
        results.append(f"  DDG-I offices: {', '.join(ddg1_offices) if ddg1_offices else '(none)'}")
        results.append(f"  DDG-II offices: {', '.join(ddg2_offices) if ddg2_offices else '(none)'}")

        # STEP 3: Find Umashankar and Shirish
        results.append("")
        results.append("=== STEP 3: Setting Up Officer Roles ===")

        cursor.execute("SELECT officer_id, name, office_id FROM officers WHERE name LIKE '%Uma%Shankar%' OR name LIKE '%Umashankar%'")
        umashankar = cursor.fetchone()

        cursor.execute("SELECT officer_id, name, office_id FROM officers WHERE name LIKE '%Shirish%' OR name LIKE '%Paliwal%'")
        shirish = cursor.fetchone()

        # Determine HRM office_id from Umashankar's office or find HRM-like office
        hrm_office_id = None
        if umashankar:
            hrm_office_id = umashankar['office_id']
        # Also check for explicit HRM office
        for off in offices:
            if 'HRM' in off['office_id'].upper() or 'HRM' in (off['office_name'] or '').upper():
                hrm_office_id = off['office_id']
                break

        # Determine Finance office_id from Shirish's office or find Finance-like office
        finance_office_id = None
        if shirish:
            finance_office_id = shirish['office_id']
        # Also check for explicit Finance office
        for off in offices:
            if 'FINANCE' in off['office_id'].upper() or 'FINANCE' in (off['office_name'] or '').upper():
                finance_office_id = off['office_id']
                break

        if umashankar:
            results.append(f"Found Umashankar: {umashankar['name']} ({umashankar['officer_id']}) - Office: {umashankar['office_id']}")

            # Remove existing roles
            cursor.execute(f"DELETE FROM officer_roles WHERE officer_id = {ph}", (umashankar['officer_id'],))

            # Assign DDG-I role (Primary)
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'DDG-I', 'GLOBAL', NULL, 1, 'ADMIN')
            """, (umashankar['officer_id'],))

            # Assign Group Head role with actual office_id as scope_value
            if hrm_office_id:
                cursor.execute(f"""
                    INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES ({ph}, 'GROUP_HEAD', 'GROUP', {ph}, 0, 'ADMIN')
                """, (umashankar['officer_id'], hrm_office_id))
                results.append(f"  - Assigned GROUP_HEAD (scope: {hrm_office_id})")

            # Assign Team Leader role
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'TEAM_LEADER', 'ASSIGNMENT', NULL, 0, 'ADMIN')
            """, (umashankar['officer_id'],))

            # Update legacy admin_role_id
            cursor.execute(f"UPDATE officers SET admin_role_id = 'DDG-I' WHERE officer_id = {ph}", (umashankar['officer_id'],))

            results.append("  - Assigned DDG-I (Primary)")
            results.append("  - Assigned TEAM_LEADER")

        else:
            results.append("Umashankar not found in database")

        if shirish:
            results.append(f"Found Shirish: {shirish['name']} ({shirish['officer_id']}) - Office: {shirish['office_id']}")

            # Remove existing roles
            cursor.execute(f"DELETE FROM officer_roles WHERE officer_id = {ph}", (shirish['officer_id'],))

            # Assign DDG-II role
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'DDG-II', 'GLOBAL', NULL, 1, 'ADMIN')
            """, (shirish['officer_id'],))

            # Assign Group Head Finance role with actual office_id as scope_value
            if finance_office_id:
                cursor.execute(f"""
                    INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES ({ph}, 'GROUP_HEAD', 'GROUP', {ph}, 0, 'ADMIN')
                """, (shirish['officer_id'], finance_office_id))
                results.append(f"  - Assigned GROUP_HEAD (scope: {finance_office_id})")

            # Update legacy admin_role_id
            cursor.execute(f"UPDATE officers SET admin_role_id = 'DDG-II' WHERE officer_id = {ph}", (shirish['officer_id'],))

            results.append("  - Assigned DDG-II (Primary)")

        else:
            results.append("Shirish Paliwal not found in database")

        # STEP 4: Setup reporting hierarchy using ACTUAL office_ids
        results.append("")
        results.append("=== STEP 4: Rebuilding Reporting Hierarchy ===")
        cursor.execute("DELETE FROM reporting_hierarchy")

        for oid in ddg1_offices:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', %s, 'DDG-I') ON CONFLICT (entity_type, entity_value) DO UPDATE SET reports_to_role = 'DDG-I'
                """, (oid,))
            else:
                cursor.execute("""
                    INSERT OR REPLACE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', ?, 'DDG-I')
                """, (oid,))
            results.append(f"  {oid} -> DDG-I")

        for oid in ddg2_offices:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', %s, 'DDG-II') ON CONFLICT (entity_type, entity_value) DO UPDATE SET reports_to_role = 'DDG-II'
                """, (oid,))
            else:
                cursor.execute("""
                    INSERT OR REPLACE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', ?, 'DDG-II')
                """, (oid,))
            results.append(f"  {oid} -> DDG-II")

        # STEP 5: Show current role assignments
        results.append("")
        results.append("=== STEP 5: Current Role Assignments ===")
        cursor.execute("""
            SELECT r.*, o.name as officer_name
            FROM officer_roles r
            JOIN officers o ON r.officer_id = o.officer_id
            ORDER BY o.name
        """)
        for row in cursor.fetchall():
            scope = f"({row['scope_value']})" if row['scope_value'] else ""
            primary = "[PRIMARY]" if row['is_primary'] else ""
            results.append(f"  {row['officer_name']}: {row['role_type']} {scope} {primary}")

        # STEP 6: Show reporting hierarchy
        results.append("")
        results.append("=== STEP 6: Reporting Hierarchy ===")
        cursor.execute("SELECT entity_type, entity_value, reports_to_role FROM reporting_hierarchy ORDER BY reports_to_role, entity_value")
        for row in cursor.fetchall():
            results.append(f"  {row['entity_value']} ({row['entity_type']}) -> {row['reports_to_role']}")

        results.append("")
        results.append("=== Role setup complete! ===")
        results.append("")
        results.append("IMPORTANT: Please log out and log back in to see the updated roles.")

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Role Setup Results</title>
        <style>
            body { font-family: monospace; padding: 20px; background: #f5f5f5; }
            pre { background: #222; color: #0f0; padding: 20px; border-radius: 5px; overflow-x: auto; }
            a { color: #007bff; }
        </style>
    </head>
    <body>
        <h2>Role Setup Results</h2>
        <pre>""" + "\n".join(results) + """</pre>
        <p><a href="/admin/roles">Go to Role Management</a></p>
        <p><a href="/dashboard">Go to Dashboard</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_page(request: Request):
    """
    Comprehensive diagnostic page showing all data mappings.
    Helps identify role and office mapping issues.
    """
    user, redirect = require_admin_access(request)
    if redirect:
        return redirect

    from app.roles import get_user_roles

    results = []
    results.append("=" * 80)
    results.append("COMPREHENSIVE DIAGNOSTIC REPORT")
    results.append("=" * 80)

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Current User Info
        results.append("\n" + "=" * 60)
        results.append("1. CURRENT USER INFO")
        results.append("=" * 60)
        results.append(f"  Officer ID: {user['officer_id']}")
        results.append(f"  Name: {user['name']}")
        results.append(f"  Email: {user['email']}")
        results.append(f"  Office ID: {user['office_id']}")
        results.append(f"  Designation: {user['designation']}")
        results.append(f"  Admin Role ID: {user.get('admin_role_id', 'None')}")
        results.append(f"  Active Role: {user.get('active_role', 'None')}")
        results.append(f"  Is Admin: {user.get('is_admin', False)}")
        results.append(f"  Computed Role: {user.get('role', 'None')}")
        results.append(f"  Role Display: {user.get('role_display', 'None')}")
        results.append(f"  Permissions: {user.get('permissions', [])}")
        results.append(f"\n  Available Roles from get_user_roles():")
        for role in user.get('roles', []):
            results.append(f"    - {role['role_type']} (scope: {role.get('scope_type', 'N/A')}={role.get('scope_value', 'N/A')})")

        # 2. All Offices
        results.append("\n" + "=" * 60)
        results.append("2. ALL OFFICES (from offices table)")
        results.append("=" * 60)
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = cursor.fetchall()
        for row in offices:
            results.append(f"  {row['office_id']} -> {row['office_name']}")

        # 3. All Officers with their Office IDs
        results.append("\n" + "=" * 60)
        results.append("3. ALL OFFICERS (with office_id and admin_role_id)")
        results.append("=" * 60)
        cursor.execute("""
            SELECT officer_id, name, email, office_id, designation, admin_role_id, is_active
            FROM officers
            ORDER BY office_id, name
        """)
        officers = cursor.fetchall()
        for row in officers:
            active_mark = "[ACTIVE]" if row['is_active'] else "[INACTIVE]"
            admin_role = row['admin_role_id'] if row['admin_role_id'] else "None"
            results.append(f"  {row['officer_id']}: {row['name']}")
            results.append(f"      Office: {row['office_id']}, Admin Role: {admin_role} {active_mark}")

        # 4. All Officer Roles
        results.append("\n" + "=" * 60)
        results.append("4. ALL OFFICER_ROLES (role assignments)")
        results.append("=" * 60)
        cursor.execute("""
            SELECT r.*, o.name as officer_name, o.office_id as officer_office
            FROM officer_roles r
            JOIN officers o ON r.officer_id = o.officer_id
            ORDER BY o.name, r.role_type
        """)
        roles_data = cursor.fetchall()
        if roles_data:
            for row in roles_data:
                primary = "[PRIMARY]" if row['is_primary'] else ""
                scope = f"scope: {row['scope_type']}={row['scope_value']}" if row['scope_value'] else "no scope"
                results.append(f"  {row['officer_name']} (office: {row['officer_office']})")
                results.append(f"      Role: {row['role_type']}, {scope} {primary}")
        else:
            results.append("  NO ROLES FOUND IN officer_roles TABLE!")

        # 5. Reporting Hierarchy
        results.append("\n" + "=" * 60)
        results.append("5. REPORTING_HIERARCHY (Office->DDG mapping)")
        results.append("=" * 60)
        cursor.execute("""
            SELECT entity_type, entity_value, reports_to_role
            FROM reporting_hierarchy
            ORDER BY reports_to_role, entity_value
        """)
        hierarchy = cursor.fetchall()
        if hierarchy:
            ddg1_offices = []
            ddg2_offices = []
            for row in hierarchy:
                if row['reports_to_role'] == 'DDG-I':
                    ddg1_offices.append(row['entity_value'])
                else:
                    ddg2_offices.append(row['entity_value'])
            results.append(f"  DDG-I offices ({len(ddg1_offices)}): {', '.join(ddg1_offices)}")
            results.append(f"  DDG-II offices ({len(ddg2_offices)}): {', '.join(ddg2_offices)}")
        else:
            results.append("  NO ENTRIES IN reporting_hierarchy TABLE!")

        # 6. Team Leader Assignments
        results.append("\n" + "=" * 60)
        results.append("6. TEAM LEADER ASSIGNMENTS")
        results.append("=" * 60)
        cursor.execute("""
            SELECT DISTINCT a.team_leader_officer_id, o.name, o.office_id
            FROM assignments a
            JOIN officers o ON a.team_leader_officer_id = o.officer_id
            WHERE a.team_leader_officer_id IS NOT NULL
            ORDER BY o.name
        """)
        team_leaders = cursor.fetchall()
        if team_leaders:
            for row in team_leaders:
                results.append(f"  {row['name']} (ID: {row['team_leader_officer_id']}, Office: {row['office_id']})")
        else:
            results.append("  No team leaders assigned to any assignments")

        # 7. Assignments Summary
        results.append("\n" + "=" * 60)
        results.append("7. ASSIGNMENTS SUMMARY (by office_id)")
        results.append("=" * 60)
        cursor.execute("""
            SELECT office_id, COUNT(*) as count
            FROM assignments
            GROUP BY office_id
            ORDER BY office_id
        """)
        assignment_summary = cursor.fetchall()
        if assignment_summary:
            for row in assignment_summary:
                results.append(f"  {row['office_id']}: {row['count']} assignments")
        else:
            results.append("  No assignments found")

        # 8. Sample Assignments Detail
        results.append("\n" + "=" * 60)
        results.append("8. SAMPLE ASSIGNMENTS (first 10)")
        results.append("=" * 60)
        cursor.execute("""
            SELECT a.id, a.assignment_no, a.office_id, a.team_leader_officer_id, a.type,
                   tl.name as team_leader_name
            FROM assignments a
            LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
            ORDER BY a.id
            LIMIT 10
        """)
        sample_assignments = cursor.fetchall()
        if sample_assignments:
            for row in sample_assignments:
                tl_name = row['team_leader_name'] if row['team_leader_name'] else "None"
                results.append(f"  #{row['id']} ({row['assignment_no']})")
                results.append(f"      Office: {row['office_id']}, TL: {tl_name}, Type: {row['type']}")
        else:
            results.append("  No assignments found")

        # 9. Cross-check: Office IDs in assignments vs offices table
        results.append("\n" + "=" * 60)
        results.append("9. DATA INTEGRITY CHECK")
        results.append("=" * 60)

        # Get all unique office_ids from assignments
        cursor.execute("SELECT DISTINCT office_id FROM assignments")
        assignment_offices = set(row['office_id'] for row in cursor.fetchall())

        # Get all office_ids from offices table
        cursor.execute("SELECT office_id FROM offices")
        valid_offices = set(row['office_id'] for row in cursor.fetchall())

        # Get all entity_values from reporting_hierarchy
        cursor.execute("SELECT entity_value FROM reporting_hierarchy WHERE entity_type = 'OFFICE'")
        hierarchy_offices = set(row['entity_value'] for row in cursor.fetchall())

        # Get all scope_values from officer_roles
        cursor.execute("SELECT DISTINCT scope_value FROM officer_roles WHERE scope_value IS NOT NULL")
        role_scope_values = set(row['scope_value'] for row in cursor.fetchall())

        # Check for mismatches
        orphan_assignment_offices = assignment_offices - valid_offices
        if orphan_assignment_offices:
            results.append(f"  [WARNING] Assignments with invalid office_id: {orphan_assignment_offices}")
        else:
            results.append("  [OK] All assignment office_ids exist in offices table")

        missing_hierarchy = valid_offices - hierarchy_offices
        if missing_hierarchy:
            results.append(f"  [WARNING] Offices NOT in reporting_hierarchy: {missing_hierarchy}")
        else:
            results.append("  [OK] All offices have reporting hierarchy entries")

        invalid_scope = role_scope_values - valid_offices
        if invalid_scope:
            results.append(f"  [WARNING] officer_roles.scope_value NOT matching offices: {invalid_scope}")
        else:
            results.append("  [OK] All officer_role scope_values match offices")

        # 10. Check current user's office mapping
        results.append("\n" + "=" * 60)
        results.append("10. CURRENT USER ROLE RESOLUTION DEBUG")
        results.append("=" * 60)

        user_office = user['office_id']
        results.append(f"  User's office_id: {user_office}")

        # Check if office exists
        cursor.execute(f"SELECT office_id, office_name FROM offices WHERE office_id = {ph()}", (user_office,))
        office_row = cursor.fetchone()
        if office_row:
            results.append(f"  [OK] Office exists: {office_row['office_name']}")
        else:
            results.append(f"  [ERROR] Office ID '{user_office}' NOT FOUND in offices table!")

        # Check reporting hierarchy
        cursor.execute(f"SELECT reports_to_role FROM reporting_hierarchy WHERE entity_value = {ph()}", (user_office,))
        hierarchy_row = cursor.fetchone()
        if hierarchy_row:
            results.append(f"  [OK] Office reports to: {hierarchy_row['reports_to_role']}")
        else:
            results.append(f"  [ERROR] Office '{user_office}' NOT in reporting_hierarchy!")

        # Check user's role entries
        cursor.execute(f"SELECT * FROM officer_roles WHERE officer_id = {ph()}", (user['officer_id'],))
        user_roles_db = cursor.fetchall()
        if user_roles_db:
            results.append(f"  User has {len(user_roles_db)} role(s) in officer_roles:")
            for role in user_roles_db:
                results.append(f"    - {role['role_type']} (scope: {role['scope_type']}={role['scope_value']})")
        else:
            results.append("  [INFO] No entries in officer_roles for this user")
            results.append("         Roles will be determined from admin_role_id and team assignments")

    results.append("\n" + "=" * 80)
    results.append("END OF DIAGNOSTIC REPORT")
    results.append("=" * 80)

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>System Diagnostics</title>
        <style>
            body { font-family: monospace; padding: 20px; background: #1a1a2e; color: #eee; }
            pre {
                background: #16213e;
                color: #0f0;
                padding: 20px;
                border-radius: 5px;
                overflow-x: auto;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            h2 { color: #e94560; }
            a { color: #0f4c75; background: #eee; padding: 5px 10px; text-decoration: none; border-radius: 3px; }
            a:hover { background: #fff; }
            .actions { margin: 20px 0; }
            .actions a { margin-right: 10px; }
        </style>
    </head>
    <body>
        <h2>System Diagnostics</h2>
        <div class="actions">
            <a href="/admin/setup-roles">Run Role Setup</a>
            <a href="/admin/diagnostics">Refresh</a>
            <a href="/dashboard">Dashboard</a>
            <a href="/logout">Logout & Re-login</a>
        </div>
        <pre>""" + "\n".join(results) + """</pre>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
