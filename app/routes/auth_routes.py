"""
Authentication routes: login, logout.
"""
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import authenticate_officer, create_session, delete_session, serialize_session, deserialize_session
from app.config import SESSION_COOKIE_NAME
from app.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display login page."""
    # If already logged in, redirect to dashboard
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    """Handle login form submission."""
    officer = authenticate_officer(email, password)

    if not officer:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=401
        )

    # Create session and set cookie
    session_id = create_session(officer['officer_id'])
    token = serialize_session(session_id)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24  # 24 hours
    )

    return response


@router.get("/logout")
async def logout(request: Request):
    """Log out the current user."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        session_id = deserialize_session(token)
        if session_id:
            delete_session(session_id)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
