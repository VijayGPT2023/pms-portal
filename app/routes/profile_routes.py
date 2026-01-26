"""
User Profile routes: view profile, change password.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db
from app.dependencies import get_current_user
from app.templates_config import templates
from app.auth import hash_password, verify_password

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
async def view_profile(request: Request):
    """Display user's own profile."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get full officer details
        cursor.execute("""
            SELECT o.*, off.office_name
            FROM officers o
            LEFT JOIN offices off ON o.office_id = off.office_id
            WHERE o.officer_id = ?
        """, (user['officer_id'],))
        officer = dict(cursor.fetchone())

        # Get all roles for this officer
        cursor.execute("""
            SELECT role_id, scope, scope_value, is_primary, effective_from
            FROM officer_roles
            WHERE officer_id = ? AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
            ORDER BY is_primary DESC, effective_from DESC
        """, (user['officer_id'],))
        roles = [dict(row) for row in cursor.fetchall()]

        # Get assignment count
        cursor.execute("""
            SELECT COUNT(DISTINCT rs.assignment_id) as assignment_count,
                   COALESCE(SUM(rs.share_amount), 0) as total_revenue
            FROM revenue_shares rs
            WHERE rs.officer_id = ?
        """, (user['officer_id'],))
        stats = dict(cursor.fetchone())

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "officer": officer,
            "roles": roles,
            "stats": stats,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error")
        }
    )


@router.get("/profile/change-password", response_class=HTMLResponse)
async def change_password_form(request: Request):
    """Display password change form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "user": user,
            "error": request.query_params.get("error")
        }
    )


@router.post("/profile/change-password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Process password change request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Validate new password
    if len(new_password) < 8:
        return RedirectResponse(
            url="/profile/change-password?error=Password must be at least 8 characters",
            status_code=302
        )

    if new_password != confirm_password:
        return RedirectResponse(
            url="/profile/change-password?error=New passwords do not match",
            status_code=302
        )

    with get_db() as conn:
        cursor = conn.cursor()

        # Get current password hash
        cursor.execute(
            "SELECT password_hash FROM officers WHERE officer_id = ?",
            (user['officer_id'],)
        )
        row = cursor.fetchone()

        if not row:
            return RedirectResponse(
                url="/profile/change-password?error=User not found",
                status_code=302
            )

        # Verify current password
        if not verify_password(current_password, row['password_hash']):
            return RedirectResponse(
                url="/profile/change-password?error=Current password is incorrect",
                status_code=302
            )

        # Update password
        new_hash = hash_password(new_password)
        cursor.execute(
            "UPDATE officers SET password_hash = ? WHERE officer_id = ?",
            (new_hash, user['officer_id'])
        )

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (action, entity_type, entity_id, actor_id, details)
            VALUES (?, ?, ?, ?, ?)
        """, ('PASSWORD_CHANGE', 'OFFICER', user['officer_id'], user['officer_id'], 'User changed their own password'))

    return RedirectResponse(
        url="/profile?message=Password changed successfully",
        status_code=302
    )


@router.post("/profile/switch-role", response_class=HTMLResponse)
async def switch_role(
    request: Request,
    role_id: str = Form(...)
):
    """Switch active role for multi-role users."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Store selected role in session (via cookie or session update)
    # For now, we'll redirect back to dashboard with the role context
    # Full implementation would update session data

    return RedirectResponse(
        url=f"/dashboard?active_role={role_id}",
        status_code=302
    )
