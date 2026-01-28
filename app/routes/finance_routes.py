"""
Finance routes: Invoice requests and payment tracking.
Manages 80-20 revenue recognition workflow.
"""
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user, is_admin, is_head
from app.templates_config import templates

router = APIRouter()


def is_finance_officer(user):
    """Check if user has Finance role."""
    admin_role = (user.get('admin_role_id', '') or '').upper()
    return admin_role in ['ADMIN', 'FINANCE', 'ACCOUNTS', 'DG', 'DDG', 'DDG-I', 'DDG-II']


def generate_invoice_request_number(office_id: str) -> str:
    """Generate unique invoice request number: INV-OFFICE-YYYYMM-NNN"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = date.today()
        prefix = f"INV-{office_id}-{today.strftime('%Y%m')}"

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
        return f"{prefix}-{next_num:03d}"


@router.get("", response_class=HTMLResponse)
async def finance_dashboard(request: Request):
    """Display Finance dashboard with pending invoices."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not is_finance_officer(user):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get pending invoice requests
        cursor.execute("""
            SELECT ir.*, a.assignment_no, a.title, a.office_id, a.total_value,
                   o.name as requested_by_name, m.title as milestone_title
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            LEFT JOIN milestones m ON ir.milestone_id = m.id
            WHERE ir.status = 'PENDING'
            ORDER BY ir.created_at DESC
        """)
        pending_invoices = [dict(row) for row in cursor.fetchall()]

        # Get recently approved invoices
        cursor.execute("""
            SELECT ir.*, a.assignment_no, a.title, a.office_id,
                   o.name as requested_by_name, ao.name as approved_by_name
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            LEFT JOIN officers ao ON ir.approved_by = ao.officer_id
            WHERE ir.status IN ('APPROVED', 'INVOICED')
            ORDER BY ir.approved_at DESC
            LIMIT 20
        """)
        approved_invoices = [dict(row) for row in cursor.fetchall()]

        # Get summary stats
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN status = 'PENDING' THEN 1 END) as pending_count,
                COUNT(CASE WHEN status = 'APPROVED' THEN 1 END) as approved_count,
                COALESCE(SUM(CASE WHEN status = 'PENDING' THEN invoice_amount ELSE 0 END), 0) as pending_value,
                COALESCE(SUM(CASE WHEN status = 'APPROVED' THEN invoice_amount ELSE 0 END), 0) as approved_value
            FROM invoice_requests
        """)
        stats = dict(cursor.fetchone())

    return templates.TemplateResponse("finance_dashboard.html", {
        "request": request,
        "user": user,
        "pending_invoices": pending_invoices,
        "approved_invoices": approved_invoices,
        "stats": stats
    })


@router.get("/invoice-request/{assignment_id}", response_class=HTMLResponse)
async def invoice_request_form(request: Request, assignment_id: int, milestone_id: Optional[int] = None):
    """Display invoice request form for TL."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get assignment
        cursor.execute("""
            SELECT a.*, o.name as tl_name
            FROM assignments a
            LEFT JOIN officers o ON a.team_leader_officer_id = o.officer_id
            WHERE a.id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            return RedirectResponse(url="/dashboard", status_code=302)

        assignment = dict(assignment)

        # Verify user is TL or head
        if assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Get milestones
        cursor.execute("""
            SELECT * FROM milestones WHERE assignment_id = ?
            ORDER BY milestone_no
        """, (assignment_id,))
        milestones = [dict(row) for row in cursor.fetchall()]

        # Get existing invoice requests
        cursor.execute("""
            SELECT ir.*, m.title as milestone_title
            FROM invoice_requests ir
            LEFT JOIN milestones m ON ir.milestone_id = m.id
            WHERE ir.assignment_id = ?
            ORDER BY ir.created_at DESC
        """, (assignment_id,))
        existing_requests = [dict(row) for row in cursor.fetchall()]

        # Calculate remaining value to invoice
        cursor.execute("""
            SELECT COALESCE(SUM(invoice_amount), 0) as total_invoiced
            FROM invoice_requests
            WHERE assignment_id = ? AND status != 'REJECTED'
        """, (assignment_id,))
        total_invoiced = cursor.fetchone()['total_invoiced'] or 0
        total_value = assignment.get('total_value') or assignment.get('gross_value') or 0
        remaining = total_value - total_invoiced

        # Get current FY
        today = date.today()
        if today.month >= 4:
            fy = f"{today.year}-{str(today.year + 1)[2:]}"
        else:
            fy = f"{today.year - 1}-{str(today.year)[2:]}"

    return templates.TemplateResponse("invoice_request_form.html", {
        "request": request,
        "user": user,
        "assignment": assignment,
        "milestones": milestones,
        "existing_requests": existing_requests,
        "selected_milestone_id": milestone_id,
        "remaining_value": remaining,
        "total_invoiced": total_invoiced,
        "current_fy": fy
    })


@router.post("/invoice-request/{assignment_id}")
async def submit_invoice_request(
    request: Request,
    assignment_id: int,
    invoice_amount: float = Form(...),
    invoice_type: str = Form(...),
    milestone_id: Optional[int] = Form(None),
    fy_period: str = Form(...),
    description: str = Form("")
):
    """TL submits invoice request for Finance approval."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify user is TL
        cursor.execute("""
            SELECT team_leader_officer_id, office_id FROM assignments WHERE id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment or assignment['team_leader_officer_id'] != user['officer_id']:
            if not (is_admin(user) or is_head(user)):
                return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Generate request number
        request_number = generate_invoice_request_number(assignment['office_id'])

        # Insert invoice request
        cursor.execute("""
            INSERT INTO invoice_requests
            (request_number, assignment_id, milestone_id, invoice_type, invoice_amount,
             fy_period, description, status, requested_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (
            request_number,
            assignment_id,
            milestone_id if milestone_id else None,
            invoice_type,
            invoice_amount,
            fy_period,
            description,
            user['officer_id']
        ))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'invoice_request', ?, ?, 'Invoice request submitted')
        """, (user['officer_id'], assignment_id, f"amount={invoice_amount}, type={invoice_type}"))

    return RedirectResponse(url=f"/finance/invoice-request/{assignment_id}?success=submitted", status_code=302)


@router.post("/invoice/{request_id}/approve")
async def approve_invoice_request(request: Request, request_id: int):
    """Finance approves invoice request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not is_finance_officer(user):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice request details
        cursor.execute("""
            SELECT ir.*, a.office_id, a.total_value
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE ir.id = ?
        """, (request_id,))
        invoice_req = cursor.fetchone()
        if not invoice_req:
            return RedirectResponse(url="/finance", status_code=302)

        invoice_req = dict(invoice_req)

        # Calculate 80% revenue recognition
        revenue_80 = invoice_req['invoice_amount'] * 0.8

        # Update invoice request
        cursor.execute("""
            UPDATE invoice_requests
            SET status = 'APPROVED',
                approved_by = ?,
                approved_at = CURRENT_TIMESTAMP,
                revenue_recognized_80 = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], revenue_80, request_id))

        # Update milestone if linked
        if invoice_req['milestone_id']:
            cursor.execute("""
                UPDATE milestones
                SET invoice_raised = 1,
                    invoice_raised_date = CURRENT_DATE,
                    invoice_amount = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (invoice_req['invoice_amount'], invoice_req['milestone_id']))

        # Update assignment invoice tracking
        cursor.execute("""
            UPDATE assignments
            SET invoice_amount = COALESCE(invoice_amount, 0) + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (invoice_req['invoice_amount'], invoice_req['assignment_id']))

        # Create revenue ledger entries for 80% recognition
        cursor.execute("""
            SELECT officer_id, share_percent FROM revenue_shares
            WHERE assignment_id = ?
        """, (invoice_req['assignment_id'],))
        shares = cursor.fetchall()

        for share in shares:
            officer_revenue = revenue_80 * (share['share_percent'] / 100)
            cursor.execute("""
                INSERT INTO officer_revenue_ledger
                (officer_id, assignment_id, invoice_request_id, revenue_type,
                 share_percent, amount, fy_period, transaction_date, remarks)
                VALUES (?, ?, ?, 'INVOICE_80', ?, ?, ?, CURRENT_DATE, '80% revenue on invoice approval')
            """, (
                share['officer_id'],
                invoice_req['assignment_id'],
                request_id,
                share['share_percent'],
                officer_revenue,
                invoice_req['fy_period']
            ))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'APPROVE', 'invoice_request', ?, 'Invoice approved, 80%% revenue recognized')
        """, (user['officer_id'], request_id))

    return RedirectResponse(url="/finance?success=approved", status_code=302)


@router.post("/invoice/{request_id}/reject")
async def reject_invoice_request(
    request: Request,
    request_id: int,
    rejection_remarks: str = Form(...)
):
    """Finance rejects invoice request."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not is_finance_officer(user):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE invoice_requests
            SET status = 'REJECTED',
                approved_by = ?,
                approved_at = CURRENT_TIMESTAMP,
                approval_remarks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], rejection_remarks, request_id))

        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'REJECT', 'invoice_request', ?, ?)
        """, (user['officer_id'], request_id, rejection_remarks))

    return RedirectResponse(url="/finance", status_code=302)


@router.get("/payment/{invoice_id}", response_class=HTMLResponse)
async def payment_form(request: Request, invoice_id: int):
    """Display payment recording form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not is_finance_officer(user):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ir.*, a.assignment_no, a.title, a.office_id,
                   o.name as requested_by_name
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            WHERE ir.id = ?
        """, (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            return RedirectResponse(url="/finance", status_code=302)

        # Get existing payments
        cursor.execute("""
            SELECT * FROM payment_receipts
            WHERE invoice_request_id = ?
            ORDER BY receipt_date DESC
        """, (invoice_id,))
        payments = [dict(row) for row in cursor.fetchall()]

        total_paid = sum(p['amount_received'] for p in payments)
        remaining = (invoice['invoice_amount'] or 0) - total_paid

    return templates.TemplateResponse("payment_form.html", {
        "request": request,
        "user": user,
        "invoice": dict(invoice),
        "payments": payments,
        "total_paid": total_paid,
        "remaining": remaining
    })


@router.post("/payment/{invoice_id}")
async def record_payment(
    request: Request,
    invoice_id: int,
    amount_received: float = Form(...),
    receipt_date: str = Form(...),
    payment_mode: str = Form(...),
    reference_number: str = Form(""),
    remarks: str = Form("")
):
    """Record payment receipt - triggers 20% revenue recognition."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not is_finance_officer(user):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice details
        cursor.execute("""
            SELECT ir.*, a.office_id
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE ir.id = ?
        """, (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            return RedirectResponse(url="/finance", status_code=302)

        invoice = dict(invoice)

        # Generate receipt number
        today = date.today()
        prefix = f"RCP-{invoice['office_id']}-{today.strftime('%Y%m')}"
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_num FROM payment_receipts
                WHERE receipt_number LIKE %s
            """, (f"{prefix}%",))
        else:
            cursor.execute("""
                SELECT COUNT(*) + 1 as next_num FROM payment_receipts
                WHERE receipt_number LIKE ?
            """, (f"{prefix}%",))
        next_num = cursor.fetchone()['next_num']
        receipt_number = f"{prefix}-{next_num:03d}"

        # Get FY period
        receipt_dt = datetime.strptime(receipt_date, '%Y-%m-%d').date()
        if receipt_dt.month >= 4:
            fy = f"{receipt_dt.year}-{str(receipt_dt.year + 1)[2:]}"
        else:
            fy = f"{receipt_dt.year - 1}-{str(receipt_dt.year)[2:]}"

        # Calculate 20% revenue recognition
        revenue_20 = amount_received * 0.2

        # Insert payment receipt
        cursor.execute("""
            INSERT INTO payment_receipts
            (receipt_number, invoice_request_id, amount_received, receipt_date,
             payment_mode, reference_number, fy_period, remarks, revenue_recognized_20, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            receipt_number,
            invoice_id,
            amount_received,
            receipt_date,
            payment_mode,
            reference_number,
            fy,
            remarks,
            revenue_20,
            user['officer_id']
        ))

        payment_id = cursor.lastrowid

        # Update milestone if linked
        if invoice['milestone_id']:
            cursor.execute("""
                UPDATE milestones
                SET payment_received = 1,
                    payment_received_date = ?,
                    status = 'Completed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (receipt_date, invoice['milestone_id']))

        # Update assignment payment tracking
        cursor.execute("""
            UPDATE assignments
            SET amount_received = COALESCE(amount_received, 0) + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (amount_received, invoice['assignment_id']))

        # Create revenue ledger entries for 20% recognition
        cursor.execute("""
            SELECT officer_id, share_percent FROM revenue_shares
            WHERE assignment_id = ?
        """, (invoice['assignment_id'],))
        shares = cursor.fetchall()

        for share in shares:
            officer_revenue = revenue_20 * (share['share_percent'] / 100)
            cursor.execute("""
                INSERT INTO officer_revenue_ledger
                (officer_id, assignment_id, invoice_request_id, payment_receipt_id,
                 revenue_type, share_percent, amount, fy_period, transaction_date, remarks)
                VALUES (?, ?, ?, ?, 'PAYMENT_20', ?, ?, ?, ?, '20% revenue on payment receipt')
            """, (
                share['officer_id'],
                invoice['assignment_id'],
                invoice_id,
                payment_id,
                share['share_percent'],
                officer_revenue,
                fy,
                receipt_date
            ))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'payment_receipt', ?, ?, 'Payment recorded, 20%% revenue recognized')
        """, (user['officer_id'], invoice_id, f"amount={amount_received}, mode={payment_mode}"))

    return RedirectResponse(url=f"/finance/payment/{invoice_id}?success=recorded", status_code=302)
