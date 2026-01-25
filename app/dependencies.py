"""
Common dependencies for route handlers.
"""
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

from app.auth import validate_session, deserialize_session
from app.config import SESSION_COOKIE_NAME
from app import roles


def get_current_user(request: Request) -> Optional[dict]:
    """
    Get the current logged-in user from session cookie.
    Returns user dict or None if not authenticated.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    session_id = deserialize_session(token)
    if not session_id:
        return None

    return validate_session(session_id)


def require_auth(request: Request) -> dict:
    """
    Dependency that requires authentication.
    Raises HTTPException with redirect if not authenticated.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def auth_redirect(request: Request):
    """
    Check auth and redirect to login if not authenticated.
    Use this in route handlers for page redirects.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return user


def is_admin(user: dict) -> bool:
    """Check if user has admin role."""
    return roles.is_admin(user)


def is_head(user: dict) -> bool:
    """Check if user is RD Head or Group Head."""
    return roles.is_head(user)


def is_senior_management(user: dict) -> bool:
    """Check if user is DG/DDG level."""
    return roles.is_senior_management(user)


def is_team_leader(user: dict) -> bool:
    """Check if user is a team leader."""
    return roles.is_team_leader(user)


def has_permission(user: dict, permission: str) -> bool:
    """Check if user has a specific permission."""
    return roles.has_permission(user, permission)


def require_admin(request: Request) -> dict:
    """
    Check if user is authenticated and has admin role.
    Returns user dict or None if not admin.
    """
    user = get_current_user(request)
    if not user:
        return None
    if not is_admin(user):
        return None
    return user


def require_permission(request: Request, permission: str):
    """
    Check if user has specific permission.
    Returns (user, None) if authorized, (None, redirect) otherwise.
    """
    user = get_current_user(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=302)
    if not has_permission(user, permission):
        return None, RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)
    return user, None


def require_head_or_above(request: Request):
    """
    Check if user is Head, DDG, DG or Admin.
    Returns (user, None) if authorized, (None, redirect) otherwise.
    """
    user = get_current_user(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=302)
    if not (is_admin(user) or is_head(user) or is_senior_management(user)):
        return None, RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)
    return user, None
