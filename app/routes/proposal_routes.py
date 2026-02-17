"""
Routes for Proposal and Workload Upload System (Feature 3G).

Handles document upload/download/delete for assignment proposals, workload documents,
TORs, work orders, and other supporting files. Also supports linking assignments
to existing proposals (for NEW activities) or uploading proposal documents (for OLD activities).
"""
import os
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user
from app.templates_config import templates
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE_MB, ALLOWED_UPLOAD_EXTENSIONS

router = APIRouter()

# Valid document types
DOCUMENT_TYPES = ['PROPOSAL', 'WORKLOAD', 'TOR', 'WORK_ORDER', 'OTHER']


def _get_assignment_or_404(cursor, assignment_id: int):
    """Fetch assignment by ID or raise 404."""
    cursor.execute("""
        SELECT a.*, off.office_name,
               tl.name as team_leader_name
        FROM assignments a
        LEFT JOIN offices off ON a.office_id = off.office_id
        LEFT JOIN officers tl ON a.team_leader_officer_id = tl.officer_id
        WHERE a.id = ?
    """, (assignment_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return row


def _get_document_or_404(cursor, document_id: int):
    """Fetch proposal document by ID or raise 404."""
    cursor.execute("""
        SELECT pd.*, o.name as uploaded_by_name
        FROM proposal_documents pd
        LEFT JOIN officers o ON pd.uploaded_by = o.officer_id
        WHERE pd.id = ?
    """, (document_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


def _get_documents_for_assignment(cursor, assignment_id: int) -> list:
    """Fetch all proposal documents for an assignment."""
    cursor.execute("""
        SELECT pd.*, o.name as uploaded_by_name
        FROM proposal_documents pd
        LEFT JOIN officers o ON pd.uploaded_by = o.officer_id
        WHERE pd.assignment_id = ?
        ORDER BY pd.created_at DESC
    """, (assignment_id,))
    return cursor.fetchall()


def _validate_file(file: UploadFile) -> tuple:
    """Validate uploaded file extension. Returns (is_valid, error_message)."""
    if not file or not file.filename:
        return False, "No file selected"
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ', '.join(ALLOWED_UPLOAD_EXTENSIONS)
        return False, f"File type '{ext}' not allowed. Allowed types: {allowed}"
    return True, ""


def _can_manage_documents(user: dict, assignment) -> bool:
    """Check if user can upload/delete documents for this assignment."""
    from app.roles import get_user_role, ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II, ROLE_RD_HEAD, ROLE_GROUP_HEAD
    role = get_user_role(user)
    if role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
        return True
    if assignment['team_leader_officer_id'] == user.get('officer_id'):
        return True
    if user.get('office_id') == assignment['office_id'] and role in [ROLE_RD_HEAD, ROLE_GROUP_HEAD]:
        return True
    if assignment.get('registered_by') == user.get('officer_id'):
        return True
    return False


# ─────────────────────────────────────────────
# 1. Document Upload Form
# ─────────────────────────────────────────────
@router.get("/upload/{assignment_id}", response_class=HTMLResponse)
async def upload_form(request: Request, assignment_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        assignment = _get_assignment_or_404(cursor, assignment_id)
        documents = _get_documents_for_assignment(cursor, assignment_id)

    return templates.TemplateResponse("proposal_upload.html", {
        "request": request, "user": user, "assignment": assignment,
        "documents": documents, "document_types": DOCUMENT_TYPES,
        "can_manage": _can_manage_documents(user, assignment),
        "max_upload_size_mb": MAX_UPLOAD_SIZE_MB,
        "allowed_extensions": ALLOWED_UPLOAD_EXTENSIONS,
    })


# ─────────────────────────────────────────────
# 2. Document Upload Handler
# ─────────────────────────────────────────────
@router.post("/upload/{assignment_id}")
async def upload_document(request: Request, assignment_id: int,
                          file: UploadFile = File(...),
                          document_type: str = Form("PROPOSAL"),
                          description: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        assignment = _get_assignment_or_404(cursor, assignment_id)

    if not _can_manage_documents(user, assignment):
        raise HTTPException(status_code=403, detail="Not authorized")

    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid document type")

    is_valid, error_msg = _validate_file(file)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    contents = await file.read()
    file_size = len(contents)
    if file_size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_UPLOAD_SIZE_MB} MB)")
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    upload_path = UPLOAD_DIR / str(assignment_id)
    os.makedirs(upload_path, exist_ok=True)

    original_filename = file.filename
    file_stem = Path(original_filename).stem
    file_ext = Path(original_filename).suffix
    final_filename = original_filename
    file_path = upload_path / final_filename
    counter = 1
    while file_path.exists():
        final_filename = f"{file_stem}_{counter}{file_ext}"
        file_path = upload_path / final_filename
        counter += 1

    with open(file_path, "wb") as f:
        f.write(contents)

    mime_type = file.content_type or "application/octet-stream"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO proposal_documents (
                assignment_id, document_type, file_name, file_path,
                file_size, mime_type, description, uploaded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (assignment_id, document_type, final_filename,
              str(file_path), file_size, mime_type,
              description.strip() if description else None,
              user['officer_id']))

    return RedirectResponse(url=f"/proposals/upload/{assignment_id}", status_code=302)


# ─────────────────────────────────────────────
# 3. Document Download
# ─────────────────────────────────────────────
@router.get("/download/{document_id}")
async def download_document(request: Request, document_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        document = _get_document_or_404(cursor, document_id)

    file_path = Path(document['file_path'])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(path=str(file_path), filename=document['file_name'],
                        media_type=document.get('mime_type') or 'application/octet-stream')


# ─────────────────────────────────────────────
# 4. Document Delete
# ─────────────────────────────────────────────
@router.post("/delete/{document_id}")
async def delete_document(request: Request, document_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        document = _get_document_or_404(cursor, document_id)
        assignment = _get_assignment_or_404(cursor, document['assignment_id'])

    if not _can_manage_documents(user, assignment):
        raise HTTPException(status_code=403, detail="Not authorized")

    assignment_id = document['assignment_id']

    file_path = Path(document['file_path'])
    if file_path.exists():
        try:
            os.remove(file_path)
        except OSError:
            pass

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proposal_documents WHERE id = ?", (document_id,))

    return RedirectResponse(url=f"/proposals/upload/{assignment_id}", status_code=302)


# ─────────────────────────────────────────────
# 5. Proposal Link Form
# ─────────────────────────────────────────────
@router.get("/link/{assignment_id}", response_class=HTMLResponse)
async def link_form(request: Request, assignment_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        assignment = _get_assignment_or_404(cursor, assignment_id)
        documents = _get_documents_for_assignment(cursor, assignment_id)

        linked_proposal = None
        linked_proposal_id = None
        try:
            linked_proposal_id = assignment['linked_proposal_id']
        except (KeyError, IndexError):
            pass
        if linked_proposal_id:
            try:
                cursor.execute("SELECT id, assignment_no, title, type FROM assignments WHERE id = ?",
                               (assignment['linked_proposal_id'],))
                linked_proposal = cursor.fetchone()
            except:
                pass

        cursor.execute("""
            SELECT DISTINCT a.id, a.assignment_no, a.title, a.type
            FROM assignments a
            INNER JOIN proposal_documents pd ON pd.assignment_id = a.id AND pd.document_type = 'PROPOSAL'
            WHERE a.id != ?
            ORDER BY a.assignment_no DESC
            LIMIT 50
        """, (assignment_id,))
        available_proposals = cursor.fetchall()

    return templates.TemplateResponse("proposal_link.html", {
        "request": request, "user": user, "assignment": assignment,
        "documents": documents, "linked_proposal": linked_proposal,
        "available_proposals": available_proposals,
        "document_types": DOCUMENT_TYPES,
        "can_manage": _can_manage_documents(user, assignment),
    })


# ─────────────────────────────────────────────
# 6. Proposal Link Handler
# ─────────────────────────────────────────────
@router.post("/link/{assignment_id}")
async def link_proposal(request: Request, assignment_id: int,
                        link_mode: str = Form(...),
                        linked_assignment_id: int = Form(None),
                        file: UploadFile = File(None),
                        description: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()
        assignment = _get_assignment_or_404(cursor, assignment_id)

    if not _can_manage_documents(user, assignment):
        raise HTTPException(status_code=403, detail="Not authorized")

    if link_mode == 'upload':
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail="No file selected")
        is_valid, error_msg = _validate_file(file)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        contents = await file.read()
        file_size = len(contents)
        if file_size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"File too large")
        if file_size == 0:
            raise HTTPException(status_code=400, detail="File is empty")

        upload_path = UPLOAD_DIR / str(assignment_id)
        os.makedirs(upload_path, exist_ok=True)
        final_filename = file.filename
        file_path = upload_path / final_filename
        counter = 1
        while file_path.exists():
            stem = Path(file.filename).stem
            ext = Path(file.filename).suffix
            final_filename = f"{stem}_{counter}{ext}"
            file_path = upload_path / final_filename
            counter += 1

        with open(file_path, "wb") as f:
            f.write(contents)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO proposal_documents (
                    assignment_id, document_type, file_name, file_path,
                    file_size, mime_type, description, uploaded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (assignment_id, 'PROPOSAL', final_filename, str(file_path),
                  file_size, file.content_type or "application/octet-stream",
                  description.strip() if description else None, user['officer_id']))

    elif link_mode == 'link':
        if not linked_assignment_id:
            raise HTTPException(status_code=400, detail="No assignment selected")
        if linked_assignment_id == assignment_id:
            raise HTTPException(status_code=400, detail="Cannot link to itself")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM assignments WHERE id = ?", (linked_assignment_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Target assignment not found")
            cursor.execute("""
                UPDATE assignments SET linked_proposal_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (linked_assignment_id, assignment_id))
    else:
        raise HTTPException(status_code=400, detail="Invalid link mode")

    return RedirectResponse(url=f"/proposals/link/{assignment_id}", status_code=302)


# ─────────────────────────────────────────────
# 7. Proposal List
# ─────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def proposal_list(request: Request, office: str = None,
                        type: str = None, has_proposal: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["1=1"]
        params = []

        if office:
            conditions.append("a.office_id = ?")
            params.append(office)
        if type:
            conditions.append("a.type = ?")
            params.append(type)

        from app.roles import get_user_role, ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II
        role = get_user_role(user)
        if role not in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
            conditions.append("a.office_id = ?")
            params.append(user['office_id'])

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT a.id, a.assignment_no, a.title, a.type, a.office_id,
                   off.office_name, a.linked_proposal_id,
                   linked.assignment_no as linked_assignment_no,
                   linked.title as linked_title,
                   (SELECT COUNT(*) FROM proposal_documents pd WHERE pd.assignment_id = a.id) as doc_count
            FROM assignments a
            LEFT JOIN offices off ON a.office_id = off.office_id
            LEFT JOIN assignments linked ON a.linked_proposal_id = linked.id
            WHERE {where_clause}
        """

        if has_proposal == 'yes':
            query += " AND ((SELECT COUNT(*) FROM proposal_documents pd WHERE pd.assignment_id = a.id AND pd.document_type = 'PROPOSAL') > 0 OR a.linked_proposal_id IS NOT NULL)"
        elif has_proposal == 'no':
            query += " AND (SELECT COUNT(*) FROM proposal_documents pd WHERE pd.assignment_id = a.id AND pd.document_type = 'PROPOSAL') = 0 AND a.linked_proposal_id IS NULL"

        query += " ORDER BY a.assignment_no DESC"
        cursor.execute(query, params)
        assignments = cursor.fetchall()

        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_name")
        offices = cursor.fetchall()

    return templates.TemplateResponse("proposal_list.html", {
        "request": request, "user": user, "assignments": assignments,
        "offices": offices, "filter_office": office, "filter_type": type,
        "filter_has_proposal": has_proposal,
    })


# ─────────────────────────────────────────────
# 8. API: Search Activities for Linking
# ─────────────────────────────────────────────
@router.get("/api/search-activities")
async def search_activities(request: Request, q: str = "", limit: int = 20):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if not q or len(q.strip()) < 2:
        return JSONResponse(content=[])

    search_term = f"%{q.strip()}%"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, assignment_no, title, type
            FROM assignments
            WHERE (assignment_no LIKE ? OR title LIKE ?)
            ORDER BY assignment_no DESC
            LIMIT ?
        """, (search_term, search_term, limit))
        results = [{"id": r['id'], "assignment_no": r['assignment_no'],
                     "title": r['title'], "type": r['type']} for r in cursor.fetchall()]

    return JSONResponse(content=results)
