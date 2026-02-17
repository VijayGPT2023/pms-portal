"""
Routes for Client Database Management (3A) and Multi-Client Assignments (3B).
Clients are managed as a master table. Each assignment can have multiple clients
treated as sub-activities with individual billing shares.
"""
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.database import get_db, USE_POSTGRES, generate_client_code
from app.dependencies import get_current_user
from app.templates_config import templates
from app.config import CLIENT_TYPE_OPTIONS

router = APIRouter()


# ─────────────────────────────────────────────
# Client Master CRUD
# ─────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def client_list(request: Request, search: str = None, client_type: str = None, city: str = None):
    """List all clients with search/filter."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        conditions = ["c.is_active = 1"]
        params = []

        if search:
            conditions.append("(c.client_name LIKE ? OR c.client_code LIKE ? OR c.contact_person LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])
        if client_type:
            conditions.append("c.client_type = ?")
            params.append(client_type)
        if city:
            conditions.append("c.city LIKE ?")
            params.append(f"%{city}%")

        where = " AND ".join(conditions)
        cursor.execute(f"""
            SELECT c.*,
                   (SELECT COUNT(*) FROM assignment_clients ac WHERE ac.client_id = c.id) as assignment_count,
                   (SELECT COALESCE(SUM(a.total_value), 0) FROM assignments a
                    JOIN assignment_clients ac ON a.id = ac.assignment_id
                    WHERE ac.client_id = c.id) as total_value
            FROM clients c
            WHERE {where}
            ORDER BY c.client_name
        """, params)
        clients = cursor.fetchall()

    return templates.TemplateResponse("client_list.html", {
        "request": request, "user": user, "clients": clients,
        "filter_search": search, "filter_type": client_type, "filter_city": city,
        "client_types": CLIENT_TYPE_OPTIONS,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_client_form(request: Request):
    """Client creation form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("client_form.html", {
        "request": request, "user": user, "client": None,
        "client_types": CLIENT_TYPE_OPTIONS, "is_edit": False,
    })


@router.post("/new")
async def create_client(request: Request,
                        client_name: str = Form(...),
                        client_type: str = Form("Others"),
                        address: str = Form(""),
                        city: str = Form(""),
                        state: str = Form(""),
                        contact_person: str = Form(""),
                        contact_email: str = Form(""),
                        contact_phone: str = Form(""),
                        gstin: str = Form(""),
                        pan: str = Form("")):
    """Create a new client."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    client_code = generate_client_code(client_name, client_type)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clients (client_code, client_name, client_type, address, city, state,
                                 contact_person, contact_email, contact_phone, gstin, pan, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (client_code, client_name.strip(), client_type,
              address.strip() or None, city.strip() or None, state.strip() or None,
              contact_person.strip() or None, contact_email.strip() or None,
              contact_phone.strip() or None, gstin.strip() or None, pan.strip() or None,
              user['officer_id']))

    return RedirectResponse(url="/clients/", status_code=302)


@router.get("/{client_id}/edit", response_class=HTMLResponse)
async def edit_client_form(request: Request, client_id: int):
    """Edit client form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

    return templates.TemplateResponse("client_form.html", {
        "request": request, "user": user, "client": client,
        "client_types": CLIENT_TYPE_OPTIONS, "is_edit": True,
    })


@router.post("/{client_id}/edit")
async def update_client(request: Request, client_id: int,
                        client_name: str = Form(...),
                        client_type: str = Form("Others"),
                        address: str = Form(""),
                        city: str = Form(""),
                        state: str = Form(""),
                        contact_person: str = Form(""),
                        contact_email: str = Form(""),
                        contact_phone: str = Form(""),
                        gstin: str = Form(""),
                        pan: str = Form("")):
    """Update client details."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE clients SET client_name=?, client_type=?, address=?, city=?, state=?,
                contact_person=?, contact_email=?, contact_phone=?, gstin=?, pan=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id = ?
        """, (client_name.strip(), client_type,
              address.strip() or None, city.strip() or None, state.strip() or None,
              contact_person.strip() or None, contact_email.strip() or None,
              contact_phone.strip() or None, gstin.strip() or None, pan.strip() or None,
              client_id))

    return RedirectResponse(url=f"/clients/{client_id}/view", status_code=302)


@router.get("/{client_id}/view", response_class=HTMLResponse)
async def view_client(request: Request, client_id: int):
    """View client details + all assignments."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        client = cursor.fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Get assignments for this client
        cursor.execute("""
            SELECT a.id, a.assignment_no, a.title, a.type, a.status, a.total_value,
                   a.office_id, a.invoice_amount, a.amount_received,
                   ac.sub_activity_number, ac.billing_share_percent, ac.description as sub_desc
            FROM assignments a
            JOIN assignment_clients ac ON a.id = ac.assignment_id
            WHERE ac.client_id = ?
            ORDER BY a.created_at DESC
        """, (client_id,))
        assignments = cursor.fetchall()

        # Summary stats
        cursor.execute("""
            SELECT COUNT(*) as total_assignments,
                   COALESCE(SUM(a.total_value * ac.billing_share_percent / 100), 0) as total_value,
                   COALESCE(SUM(a.invoice_amount * ac.billing_share_percent / 100), 0) as total_invoiced,
                   COALESCE(SUM(a.amount_received * ac.billing_share_percent / 100), 0) as total_received
            FROM assignments a
            JOIN assignment_clients ac ON a.id = ac.assignment_id
            WHERE ac.client_id = ?
        """, (client_id,))
        stats = cursor.fetchone()

    return templates.TemplateResponse("client_view.html", {
        "request": request, "user": user, "client": client,
        "assignments": assignments, "stats": stats,
    })


# ─────────────────────────────────────────────
# Client-Assignment Linking (Multi-client / Sub-activities)
# ─────────────────────────────────────────────

@router.get("/assignment/{assignment_id}/manage", response_class=HTMLResponse)
async def manage_assignment_clients(request: Request, assignment_id: int):
    """Manage clients for an assignment."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, off.office_name FROM assignments a
            LEFT JOIN offices off ON a.office_id = off.office_id
            WHERE a.id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Get linked clients
        cursor.execute("""
            SELECT ac.*, c.client_name, c.client_code, c.client_type, c.city
            FROM assignment_clients ac
            JOIN clients c ON ac.client_id = c.id
            WHERE ac.assignment_id = ?
            ORDER BY ac.is_primary DESC, c.client_name
        """, (assignment_id,))
        linked_clients = cursor.fetchall()

        # Get all active clients for the dropdown
        cursor.execute("SELECT id, client_code, client_name, client_type FROM clients WHERE is_active = 1 ORDER BY client_name")
        all_clients = cursor.fetchall()

    return templates.TemplateResponse("assignment_clients.html", {
        "request": request, "user": user, "assignment": assignment,
        "linked_clients": linked_clients, "all_clients": all_clients,
    })


@router.post("/assignment/{assignment_id}/add")
async def add_client_to_assignment(request: Request, assignment_id: int,
                                   client_id: int = Form(...),
                                   billing_share_percent: float = Form(100),
                                   description: str = Form(""),
                                   is_primary: int = Form(0)):
    """Add client as sub-activity to assignment."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify assignment exists
        cursor.execute("SELECT assignment_no FROM assignments WHERE id = ?", (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Count existing sub-activities to generate sub_activity_number
        cursor.execute("SELECT COUNT(*) as cnt FROM assignment_clients WHERE assignment_id = ?",
                       (assignment_id,))
        count = cursor.fetchone()['cnt']
        sub_activity_number = f"{assignment['assignment_no']}/SUB-{count + 1:02d}"

        try:
            cursor.execute("""
                INSERT INTO assignment_clients (assignment_id, client_id, sub_activity_number,
                    billing_share_percent, description, is_primary)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (assignment_id, client_id, sub_activity_number,
                  billing_share_percent, description.strip() or None, is_primary))
        except Exception:
            # Likely duplicate - client already linked
            pass

    return RedirectResponse(url=f"/clients/assignment/{assignment_id}/manage", status_code=302)


@router.post("/assignment/{assignment_id}/{link_id}/remove")
async def remove_client_from_assignment(request: Request, assignment_id: int, link_id: int):
    """Remove client-assignment link."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM assignment_clients WHERE id = ? AND assignment_id = ?",
                       (link_id, assignment_id))

    return RedirectResponse(url=f"/clients/assignment/{assignment_id}/manage", status_code=302)


# ─────────────────────────────────────────────
# Client MIS
# ─────────────────────────────────────────────

@router.get("/mis", response_class=HTMLResponse)
async def client_mis(request: Request, client_type: str = None):
    """Client MIS dashboard."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["c.is_active = 1"]
        params = []
        if client_type:
            conditions.append("c.client_type = ?")
            params.append(client_type)

        where = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT c.id, c.client_code, c.client_name, c.client_type, c.city,
                   COUNT(DISTINCT ac.assignment_id) as assignment_count,
                   COALESCE(SUM(a.total_value * ac.billing_share_percent / 100), 0) as total_value,
                   COALESCE(SUM(a.invoice_amount * ac.billing_share_percent / 100), 0) as total_invoiced,
                   COALESCE(SUM(a.amount_received * ac.billing_share_percent / 100), 0) as total_received
            FROM clients c
            LEFT JOIN assignment_clients ac ON c.id = ac.client_id
            LEFT JOIN assignments a ON ac.assignment_id = a.id
            WHERE {where}
            GROUP BY c.id, c.client_code, c.client_name, c.client_type, c.city
            ORDER BY total_value DESC
        """, params)
        client_data = cursor.fetchall()

        # Summary totals
        cursor.execute("""
            SELECT COUNT(DISTINCT c.id) as total_clients,
                   COUNT(DISTINCT ac.assignment_id) as total_assignments,
                   COALESCE(SUM(a.total_value * ac.billing_share_percent / 100), 0) as grand_total_value,
                   COALESCE(SUM(a.invoice_amount * ac.billing_share_percent / 100), 0) as grand_total_invoiced,
                   COALESCE(SUM(a.amount_received * ac.billing_share_percent / 100), 0) as grand_total_received
            FROM clients c
            LEFT JOIN assignment_clients ac ON c.id = ac.client_id
            LEFT JOIN assignments a ON ac.assignment_id = a.id
            WHERE c.is_active = 1
        """)
        totals = cursor.fetchone()

    return templates.TemplateResponse("client_mis.html", {
        "request": request, "user": user, "client_data": client_data,
        "totals": totals, "filter_type": client_type,
        "client_types": CLIENT_TYPE_OPTIONS,
    })


# ─────────────────────────────────────────────
# API: Client Search Autocomplete
# ─────────────────────────────────────────────

@router.get("/api/search")
async def search_clients(request: Request, q: str = "", limit: int = 20):
    """JSON autocomplete search for client names."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if not q or len(q.strip()) < 2:
        return JSONResponse(content=[])

    term = f"%{q.strip()}%"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_code, client_name, client_type
            FROM clients WHERE (client_name LIKE ? OR client_code LIKE ?) AND is_active = 1
            ORDER BY client_name LIMIT ?
        """, (term, term, limit))
        results = [{"id": r['id'], "client_code": r['client_code'],
                     "client_name": r['client_name'], "client_type": r['client_type']}
                    for r in cursor.fetchall()]

    return JSONResponse(content=results)
