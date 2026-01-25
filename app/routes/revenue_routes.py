"""
Revenue sharing routes: fill and update revenue shares.
"""
from pathlib import Path
from typing import List
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import json

from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def get_assignment(assignment_id: int):
    """Get assignment by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_officers_list():
    """Get list of all officers for dropdowns."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers
            WHERE is_active = 1
            ORDER BY name
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_existing_shares(assignment_id: int):
    """Get existing revenue shares for an assignment."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rs.*, o.name as officer_name
            FROM revenue_shares rs
            JOIN officers o ON rs.officer_id = o.officer_id
            WHERE rs.assignment_id = ?
            ORDER BY rs.share_percent DESC
        """, (assignment_id,))
        return [dict(row) for row in cursor.fetchall()]


@router.get("/edit/{assignment_id}", response_class=HTMLResponse)
async def revenue_share_page(request: Request, assignment_id: int):
    """Display revenue share form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    officers = get_officers_list()
    existing_shares = get_existing_shares(assignment_id)

    # Prepare existing shares as JSON for JavaScript
    existing_shares_json = json.dumps([{
        'officer_id': s['officer_id'],
        'share_percent': s['share_percent'],
        'share_amount': s['share_amount']
    } for s in existing_shares])

    return templates.TemplateResponse(
        "revenue_share_form.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "officers": officers,
            "existing_shares": existing_shares,
            "existing_shares_json": existing_shares_json
        }
    )


@router.post("/edit/{assignment_id}")
async def revenue_share_submit(request: Request, assignment_id: int):
    """Handle revenue share form submission."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return RedirectResponse(url="/dashboard", status_code=302)

    # Parse form data
    form_data = await request.form()

    # Extract shares from form
    shares = []
    i = 0
    while f'officer_id_{i}' in form_data:
        officer_id = form_data.get(f'officer_id_{i}')
        share_percent_str = form_data.get(f'share_percent_{i}', '0')

        if officer_id and share_percent_str:
            try:
                share_percent = float(share_percent_str)
                if share_percent > 0:
                    total_revenue = assignment.get('total_revenue') or assignment.get('gross_value') or 0
                    share_amount = (share_percent * total_revenue) / 100
                    shares.append({
                        'officer_id': officer_id,
                        'share_percent': share_percent,
                        'share_amount': share_amount
                    })
            except ValueError:
                pass
        i += 1

    # Validate total percentage
    total_percent = sum(s['share_percent'] for s in shares)
    if abs(total_percent - 100) > 0.01 and total_percent > 0:  # Allow small floating point errors
        officers = get_officers_list()
        existing_shares = get_existing_shares(assignment_id)
        return templates.TemplateResponse(
            "revenue_share_form.html",
            {
                "request": request,
                "user": user,
                "assignment": assignment,
                "officers": officers,
                "existing_shares": existing_shares,
                "existing_shares_json": json.dumps([]),
                "error": f"Total percentage must be 100%. Current total: {total_percent:.2f}%"
            },
            status_code=400
        )

    # Save shares to database
    with get_db() as conn:
        cursor = conn.cursor()

        # Delete existing shares
        cursor.execute("DELETE FROM revenue_shares WHERE assignment_id = ?", (assignment_id,))

        # Insert new shares
        for share in shares:
            cursor.execute("""
                INSERT INTO revenue_shares (assignment_id, officer_id, share_percent, share_amount)
                VALUES (?, ?, ?, ?)
            """, (assignment_id, share['officer_id'], share['share_percent'], share['share_amount']))

    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/api/officers", response_class=JSONResponse)
async def api_get_officers(request: Request):
    """API endpoint to get officers list."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    officers = get_officers_list()
    return JSONResponse({"officers": officers})


@router.get("/api/assignment/{assignment_id}", response_class=JSONResponse)
async def api_get_assignment(request: Request, assignment_id: int):
    """API endpoint to get assignment details."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return JSONResponse({"error": "Assignment not found"}, status_code=404)

    return JSONResponse({"assignment": assignment})
