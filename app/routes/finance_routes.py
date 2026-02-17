"""
Finance routes: Invoice requests and payment tracking.
Manages 80-20 revenue recognition workflow.

Feature 3H: Officer Invoice Request -> TL Verify -> Head Approve -> Finance Process
Feature 4A: Multi-Milestone Invoice + TL Revenue Hold
Feature 4C: Revenue on Case Basis, Expenditure on Accrual Basis

Revenue Recognition Model (Feature 4C -- Case Basis):
    Revenue is recognized on a CASE basis, meaning it is recorded when specific
    triggering events occur:
    - 80% of invoice amount is recognized when the invoice is APPROVED
      (see approve_invoice_request and allocate_officer_revenue_80 in database.py).
    - 20% of payment amount is recognized when the payment RECEIPT is recorded
      (see record_payment and allocate_officer_revenue_20 in database.py).
    This is event-driven (case basis), NOT time-based (accrual).

Expenditure Recognition Model (Feature 4C -- Accrual Basis):
    Expenditure is recognized on an ACCRUAL basis, meaning costs are recorded
    in the period they are incurred (by entry_date in expenditure_entries),
    regardless of when the actual payment is made. Each expenditure_entries row
    has an entry_date and an fy_period; reports aggregate by entry_date so that
    costs appear in the financial period they belong to, not the period in
    which cash changed hands.
"""
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db, USE_POSTGRES
from app.dependencies import get_current_user, is_admin, is_head
from app.roles import (
    is_finance_officer as _roles_is_finance_officer,
    is_finance_for_office,
    ROLE_FINANCE,
)
from app.templates_config import templates

router = APIRouter()


def is_finance_officer(user):
    """Check if user has Finance role.

    Uses the canonical check from app.roles, with a fallback to legacy
    admin_role_id values so existing Admin/DG/DDG users retain access.
    """
    if _roles_is_finance_officer(user):
        return True
    # Legacy fallback: admin-level roles can still access finance dashboard
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
    milestone_ids: Optional[str] = Form(None),
    milestone_amounts: Optional[str] = Form(None),
    fy_period: str = Form(...),
    description: str = Form("")
):
    """TL submits invoice request for Finance approval.

    Feature 4A: Supports multi-milestone invoices via milestone_ids and
    milestone_amounts (comma-separated). When multiple milestones are
    provided, records are inserted into invoice_milestone_links.
    The legacy single milestone_id field is still supported for backwards
    compatibility.

    Feature 3H: TL/Head-initiated requests have officer_request_status = 'DIRECT'.
    """
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

        # Insert invoice request (officer_request_status = 'DIRECT' for TL/Head)
        cursor.execute("""
            INSERT INTO invoice_requests
            (request_number, assignment_id, milestone_id, invoice_type, invoice_amount,
             fy_period, description, status, requested_by, officer_request_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 'DIRECT')
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

        # Get the ID of the newly inserted invoice request
        cursor.execute("""
            SELECT id FROM invoice_requests WHERE request_number = ?
        """, (request_number,))
        new_invoice = cursor.fetchone()
        invoice_request_id = new_invoice['id'] if new_invoice else None

        # Feature 4A: Link multiple milestones if provided
        if invoice_request_id and milestone_ids and milestone_amounts:
            m_ids = [mid.strip() for mid in milestone_ids.split(',') if mid.strip()]
            m_amounts = [ma.strip() for ma in milestone_amounts.split(',') if ma.strip()]

            if len(m_ids) == len(m_amounts):
                for mid_str, mamt_str in zip(m_ids, m_amounts):
                    try:
                        mid = int(mid_str)
                        mamt = float(mamt_str)

                        # Calculate revenue share percent for this milestone
                        rev_pct = (mamt / invoice_amount * 100) if invoice_amount > 0 else 0

                        # Get milestone date
                        cursor.execute("""
                            SELECT target_date FROM milestones WHERE id = ?
                        """, (mid,))
                        ms_row = cursor.fetchone()
                        ms_date = ms_row['target_date'] if ms_row else None

                        cursor.execute("""
                            INSERT INTO invoice_milestone_links
                            (invoice_request_id, milestone_id, milestone_share_amount,
                             revenue_share_percent, milestone_date)
                            VALUES (?, ?, ?, ?, ?)
                        """, (invoice_request_id, mid, mamt, rev_pct, ms_date))
                    except (ValueError, TypeError):
                        continue

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'invoice_request', ?, ?, 'Invoice request submitted')
        """, (user['officer_id'], assignment_id, f"amount={invoice_amount}, type={invoice_type}"))

    return RedirectResponse(url=f"/finance/invoice-request/{assignment_id}?success=submitted", status_code=302)


@router.post("/invoice/{request_id}/approve")
async def approve_invoice_request(request: Request, request_id: int):
    """Finance approves invoice request.

    For officer-initiated requests (officer_request_status = 'OFFICER_REQUESTED'
    or 'TL_VERIFIED'), the flow must have gone through TL verification first.
    Only requests with status 'TL_VERIFIED' or 'DIRECT' (TL/Head-initiated)
    can be approved by Finance.
    """
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

        # Feature 3H: For officer-initiated requests, require TL verification first
        officer_request_status = invoice_req.get('officer_request_status') or 'DIRECT'
        if officer_request_status == 'OFFICER_REQUESTED':
            # Officer requested but TL has not verified yet -- cannot approve
            return RedirectResponse(
                url="/finance?error=tl_verification_required",
                status_code=302
            )

        # Calculate 80% revenue recognition
        revenue_80 = invoice_req['invoice_amount'] * 0.8

        # Check for TL revenue hold (Feature 4A)
        tl_revenue_hold = invoice_req.get('tl_revenue_hold') or 0

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

        # Update milestone if linked (single milestone -- legacy support)
        if invoice_req['milestone_id']:
            cursor.execute("""
                UPDATE milestones
                SET invoice_raised = 1,
                    invoice_raised_date = CURRENT_DATE,
                    invoice_amount = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (invoice_req['invoice_amount'], invoice_req['milestone_id']))

        # Feature 4A: Update milestones linked via invoice_milestone_links
        cursor.execute("""
            SELECT milestone_id, milestone_share_amount
            FROM invoice_milestone_links
            WHERE invoice_request_id = ?
        """, (request_id,))
        linked_milestones = cursor.fetchall()
        for lm in linked_milestones:
            cursor.execute("""
                UPDATE milestones
                SET invoice_raised = 1,
                    invoice_raised_date = CURRENT_DATE,
                    invoice_amount = COALESCE(invoice_amount, 0) + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (lm['milestone_share_amount'], lm['milestone_id']))

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
            # Feature 4A: If TL has placed a revenue hold, mark ledger entries as held
            cursor.execute("""
                INSERT INTO officer_revenue_ledger
                (officer_id, assignment_id, invoice_request_id, revenue_type,
                 share_percent, amount, fy_period, transaction_date, is_held, remarks)
                VALUES (?, ?, ?, 'INVOICE_80', ?, ?, ?, CURRENT_DATE, ?,
                        '80% revenue on invoice approval')
            """, (
                share['officer_id'],
                invoice_req['assignment_id'],
                request_id,
                share['share_percent'],
                officer_revenue,
                invoice_req['fy_period'],
                1 if tl_revenue_hold else 0,
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
    """Record payment receipt - triggers 20% revenue recognition.

    Feature 4C: Revenue is recognized on a CASE basis -- the 20% revenue
    recognition is triggered by the event of recording the payment receipt,
    not by any time-based accrual schedule.
    """
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


# ============================================================
# Feature 3H: Officer Invoice Request -> TL Verify -> Head Approve -> Finance Process
# ============================================================

@router.post("/invoice-request-by-officer/{assignment_id}")
async def officer_request_invoice(
    request: Request,
    assignment_id: int,
    invoice_amount: float = Form(...),
    invoice_type: str = Form(...),
    milestone_ids: Optional[str] = Form(None),
    milestone_amounts: Optional[str] = Form(None),
    fy_period: str = Form(...),
    description: str = Form("")
):
    """Officer requests an invoice.

    Feature 3H flow:
    Officer fills in invoice details -> status = OFFICER_REQUESTED -> PENDING.
    Then TL verifies, Head approves, Finance processes.

    Also supports Feature 4A multi-milestone invoices:
    milestone_ids and milestone_amounts are comma-separated lists.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Verify the assignment exists and the officer is on the team
        cursor.execute("""
            SELECT a.id, a.office_id, a.team_leader_officer_id, a.total_value
            FROM assignments a
            WHERE a.id = ?
        """, (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            return RedirectResponse(url="/dashboard?error=not_found", status_code=302)

        assignment = dict(assignment)

        # Officer must be on the assignment team or be the TL
        officer_id = user['officer_id']
        cursor.execute("""
            SELECT id FROM assignment_team
            WHERE assignment_id = ? AND officer_id = ? AND is_active = 1
        """, (assignment_id, officer_id))
        team_member = cursor.fetchone()

        is_tl = (assignment['team_leader_officer_id'] == officer_id)

        if not team_member and not is_tl and not is_admin(user):
            return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

        # Generate request number
        request_number = generate_invoice_request_number(assignment['office_id'])

        # Insert the invoice request with officer_request_status = OFFICER_REQUESTED
        cursor.execute("""
            INSERT INTO invoice_requests
            (request_number, assignment_id, milestone_id, invoice_type, invoice_amount,
             fy_period, description, status, requested_by,
             officer_request_status, requested_by_officer_id)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 'PENDING', ?, 'OFFICER_REQUESTED', ?)
        """, (
            request_number,
            assignment_id,
            invoice_type,
            invoice_amount,
            fy_period,
            description,
            officer_id,
            officer_id,
        ))

        # Get the ID of the newly inserted invoice request
        cursor.execute("""
            SELECT id FROM invoice_requests WHERE request_number = ?
        """, (request_number,))
        new_invoice = cursor.fetchone()
        invoice_request_id = new_invoice['id'] if new_invoice else None

        # Feature 4A: Link multiple milestones if provided
        if invoice_request_id and milestone_ids and milestone_amounts:
            m_ids = [mid.strip() for mid in milestone_ids.split(',') if mid.strip()]
            m_amounts = [ma.strip() for ma in milestone_amounts.split(',') if ma.strip()]

            if len(m_ids) == len(m_amounts):
                total_milestone_amount = 0.0
                for mid_str, mamt_str in zip(m_ids, m_amounts):
                    try:
                        mid = int(mid_str)
                        mamt = float(mamt_str)
                        total_milestone_amount += mamt

                        # Calculate revenue share percent for this milestone
                        rev_pct = (mamt / invoice_amount * 100) if invoice_amount > 0 else 0

                        # Get milestone date
                        cursor.execute("""
                            SELECT target_date FROM milestones WHERE id = ?
                        """, (mid,))
                        ms_row = cursor.fetchone()
                        ms_date = ms_row['target_date'] if ms_row else None

                        cursor.execute("""
                            INSERT INTO invoice_milestone_links
                            (invoice_request_id, milestone_id, milestone_share_amount,
                             revenue_share_percent, milestone_date)
                            VALUES (?, ?, ?, ?, ?)
                        """, (invoice_request_id, mid, mamt, rev_pct, ms_date))
                    except (ValueError, TypeError):
                        continue

                # Validate: sum of milestone amounts should equal invoice amount
                # Allow small tolerance for floating point
                if abs(total_milestone_amount - invoice_amount) > 0.01:
                    # Log a warning but still proceed
                    cursor.execute("""
                        INSERT INTO activity_log
                        (actor_id, action, entity_type, entity_id, remarks)
                        VALUES (?, 'WARNING', 'invoice_request', ?,
                                'Milestone amounts sum mismatch with invoice amount')
                    """, (officer_id, invoice_request_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, new_data, remarks)
            VALUES (?, 'CREATE', 'invoice_request', ?, ?,
                    'Officer requested invoice (Feature 3H)')
        """, (
            officer_id,
            assignment_id,
            f"amount={invoice_amount}, type={invoice_type}, officer_requested=1"
        ))

    return RedirectResponse(
        url=f"/finance/invoice-request/{assignment_id}?success=officer_requested",
        status_code=302
    )


@router.post("/invoice/{request_id}/tl-verify")
async def tl_verify_invoice(request: Request, request_id: int):
    """TL verifies an officer-initiated invoice request.

    Feature 3H: Only the TL of the assignment can verify.
    Changes officer_request_status from OFFICER_REQUESTED to TL_VERIFIED.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice request with assignment details
        cursor.execute("""
            SELECT ir.*, a.team_leader_officer_id, a.office_id
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE ir.id = ?
        """, (request_id,))
        invoice_req = cursor.fetchone()
        if not invoice_req:
            return RedirectResponse(url="/finance?error=not_found", status_code=302)

        invoice_req = dict(invoice_req)

        # Only the TL of the assignment can verify
        if invoice_req['team_leader_officer_id'] != user['officer_id']:
            if not is_admin(user):
                return RedirectResponse(
                    url="/dashboard?error=unauthorized",
                    status_code=302
                )

        # Must be in OFFICER_REQUESTED status
        officer_request_status = invoice_req.get('officer_request_status') or 'DIRECT'
        if officer_request_status != 'OFFICER_REQUESTED':
            return RedirectResponse(
                url=f"/finance/invoice-request/{invoice_req['assignment_id']}?error=invalid_status",
                status_code=302
            )

        # Update to TL_VERIFIED
        cursor.execute("""
            UPDATE invoice_requests
            SET officer_request_status = 'TL_VERIFIED',
                verified_by = ?,
                verified_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user['officer_id'], request_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'VERIFY', 'invoice_request', ?,
                    'TL verified officer invoice request (Feature 3H)')
        """, (user['officer_id'], request_id))

    return RedirectResponse(
        url=f"/finance/invoice-request/{invoice_req['assignment_id']}?success=tl_verified",
        status_code=302
    )


@router.get("/finance-officer-dashboard", response_class=HTMLResponse)
async def finance_officer_dashboard(request: Request):
    """Finance Officer dashboard showing pending invoices for managed offices.

    Feature 3H: Uses the finance_officers table to determine which offices
    the current finance officer manages. Shows all pending invoices for
    those offices.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Must be a finance officer (or admin)
    if not is_finance_officer(user) and not is_admin(user):
        return RedirectResponse(url="/dashboard?error=unauthorized", status_code=302)

    officer_id = user['officer_id']

    with get_db() as conn:
        cursor = conn.cursor()

        # Get offices this finance officer manages
        cursor.execute("""
            SELECT fo.office_id, o.office_name
            FROM finance_officers fo
            JOIN offices o ON fo.office_id = o.office_id
            WHERE fo.officer_id = ? AND fo.is_active = 1
        """, (officer_id,))
        managed_offices = [dict(row) for row in cursor.fetchall()]
        managed_office_ids = [mo['office_id'] for mo in managed_offices]

        # If admin or no specific offices, show all
        if is_admin(user) and not managed_office_ids:
            cursor.execute("SELECT office_id FROM offices")
            managed_office_ids = [row['office_id'] for row in cursor.fetchall()]

        if not managed_office_ids:
            # No offices to manage
            return templates.TemplateResponse("finance_officer_dashboard.html", {
                "request": request,
                "user": user,
                "managed_offices": [],
                "pending_invoices": [],
                "officer_requested_invoices": [],
                "tl_verified_invoices": [],
                "approved_invoices": [],
                "stats": {
                    "pending_count": 0,
                    "officer_requested_count": 0,
                    "tl_verified_count": 0,
                    "approved_count": 0,
                    "pending_value": 0,
                    "approved_value": 0,
                },
            })

        # Build placeholder string for IN clause
        placeholders = ','.join(['?' for _ in managed_office_ids])

        # Get pending invoices (DIRECT or TL_VERIFIED -- ready for finance)
        cursor.execute(f"""
            SELECT ir.*, a.assignment_no, a.title, a.office_id, a.total_value,
                   o.name as requested_by_name, m.title as milestone_title
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            LEFT JOIN milestones m ON ir.milestone_id = m.id
            WHERE ir.status = 'PENDING'
              AND a.office_id IN ({placeholders})
              AND COALESCE(ir.officer_request_status, 'DIRECT') IN ('DIRECT', 'TL_VERIFIED')
            ORDER BY ir.created_at DESC
        """, tuple(managed_office_ids))
        pending_invoices = [dict(row) for row in cursor.fetchall()]

        # Get officer-requested invoices (awaiting TL verification)
        cursor.execute(f"""
            SELECT ir.*, a.assignment_no, a.title, a.office_id,
                   o.name as requested_by_name,
                   ro.name as requesting_officer_name
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            LEFT JOIN officers ro ON ir.requested_by_officer_id = ro.officer_id
            WHERE ir.status = 'PENDING'
              AND a.office_id IN ({placeholders})
              AND ir.officer_request_status = 'OFFICER_REQUESTED'
            ORDER BY ir.created_at DESC
        """, tuple(managed_office_ids))
        officer_requested_invoices = [dict(row) for row in cursor.fetchall()]

        # Get TL-verified invoices (awaiting head/finance approval)
        cursor.execute(f"""
            SELECT ir.*, a.assignment_no, a.title, a.office_id,
                   o.name as requested_by_name,
                   vo.name as verified_by_name
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            LEFT JOIN officers vo ON ir.verified_by = vo.officer_id
            WHERE ir.status = 'PENDING'
              AND a.office_id IN ({placeholders})
              AND ir.officer_request_status = 'TL_VERIFIED'
            ORDER BY ir.created_at DESC
        """, tuple(managed_office_ids))
        tl_verified_invoices = [dict(row) for row in cursor.fetchall()]

        # Get recently approved invoices
        cursor.execute(f"""
            SELECT ir.*, a.assignment_no, a.title, a.office_id,
                   o.name as requested_by_name, ao.name as approved_by_name
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            JOIN officers o ON ir.requested_by = o.officer_id
            LEFT JOIN officers ao ON ir.approved_by = ao.officer_id
            WHERE ir.status IN ('APPROVED', 'INVOICED')
              AND a.office_id IN ({placeholders})
            ORDER BY ir.approved_at DESC
            LIMIT 20
        """, tuple(managed_office_ids))
        approved_invoices = [dict(row) for row in cursor.fetchall()]

        # Get summary stats for managed offices
        cursor.execute(f"""
            SELECT
                COUNT(CASE WHEN ir.status = 'PENDING'
                           AND COALESCE(ir.officer_request_status, 'DIRECT') IN ('DIRECT', 'TL_VERIFIED')
                      THEN 1 END) as pending_count,
                COUNT(CASE WHEN ir.status = 'PENDING'
                           AND ir.officer_request_status = 'OFFICER_REQUESTED'
                      THEN 1 END) as officer_requested_count,
                COUNT(CASE WHEN ir.status = 'PENDING'
                           AND ir.officer_request_status = 'TL_VERIFIED'
                      THEN 1 END) as tl_verified_count,
                COUNT(CASE WHEN ir.status = 'APPROVED' THEN 1 END) as approved_count,
                COALESCE(SUM(CASE WHEN ir.status = 'PENDING' THEN ir.invoice_amount ELSE 0 END), 0) as pending_value,
                COALESCE(SUM(CASE WHEN ir.status = 'APPROVED' THEN ir.invoice_amount ELSE 0 END), 0) as approved_value
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE a.office_id IN ({placeholders})
        """, tuple(managed_office_ids))
        stats = dict(cursor.fetchone())

    return templates.TemplateResponse("finance_officer_dashboard.html", {
        "request": request,
        "user": user,
        "managed_offices": managed_offices,
        "pending_invoices": pending_invoices,
        "officer_requested_invoices": officer_requested_invoices,
        "tl_verified_invoices": tl_verified_invoices,
        "approved_invoices": approved_invoices,
        "stats": stats,
    })


# ============================================================
# Feature 4A: Multi-Milestone Invoice + TL Revenue Hold
# ============================================================

@router.post("/invoice/{request_id}/hold-revenue")
async def hold_revenue(request: Request, request_id: int):
    """TL places a revenue hold on an invoice.

    Feature 4A: TL can mark tl_revenue_hold = 1 on an invoice request.
    When revenue is allocated (in approve_invoice_request), entries in
    officer_revenue_ledger are marked with is_held = 1.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice request and verify TL
        cursor.execute("""
            SELECT ir.*, a.team_leader_officer_id, a.office_id
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE ir.id = ?
        """, (request_id,))
        invoice_req = cursor.fetchone()
        if not invoice_req:
            return RedirectResponse(url="/finance?error=not_found", status_code=302)

        invoice_req = dict(invoice_req)

        # Only TL of the assignment (or admin) can hold revenue
        if invoice_req['team_leader_officer_id'] != user['officer_id']:
            if not is_admin(user):
                return RedirectResponse(
                    url="/dashboard?error=unauthorized",
                    status_code=302
                )

        # Set the hold
        cursor.execute("""
            UPDATE invoice_requests
            SET tl_revenue_hold = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (request_id,))

        # If revenue was already allocated, mark existing ledger entries as held
        cursor.execute("""
            UPDATE officer_revenue_ledger
            SET is_held = 1
            WHERE invoice_request_id = ? AND revenue_type = 'INVOICE_80'
        """, (request_id,))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'HOLD', 'invoice_request', ?,
                    'TL placed revenue hold on invoice (Feature 4A)')
        """, (user['officer_id'], request_id))

    return RedirectResponse(
        url=f"/finance/invoice-request/{invoice_req['assignment_id']}?success=revenue_held",
        status_code=302
    )


@router.post("/invoice/{request_id}/release-revenue")
async def release_revenue(
    request: Request,
    request_id: int,
    milestone_release_percents: Optional[str] = Form(None),
):
    """TL releases a revenue hold on an invoice.

    Feature 4A: TL releases the hold. Updates is_held = 0 on
    officer_revenue_ledger entries, sets released_by and released_at.

    If milestone_release_percents is provided (comma-separated list of
    milestone_id:percent pairs, e.g. "5:50,6:50"), TL can specify what
    percentage of invoice value to release for each milestone. If not
    provided, releases all held revenue at 100%.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice request and verify TL
        cursor.execute("""
            SELECT ir.*, a.team_leader_officer_id, a.office_id
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE ir.id = ?
        """, (request_id,))
        invoice_req = cursor.fetchone()
        if not invoice_req:
            return RedirectResponse(url="/finance?error=not_found", status_code=302)

        invoice_req = dict(invoice_req)

        # Only TL of the assignment (or admin) can release
        if invoice_req['team_leader_officer_id'] != user['officer_id']:
            if not is_admin(user):
                return RedirectResponse(
                    url="/dashboard?error=unauthorized",
                    status_code=302
                )

        # Remove the hold on the invoice request
        cursor.execute("""
            UPDATE invoice_requests
            SET tl_revenue_hold = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (request_id,))

        if milestone_release_percents:
            # Parse milestone:percent pairs
            # Format: "milestone_id:release_percent,milestone_id:release_percent"
            # The release_percent determines what fraction of each officer's held
            # revenue for this invoice to release.
            pairs = [p.strip() for p in milestone_release_percents.split(',') if p.strip()]
            total_release_pct = 0.0
            for pair in pairs:
                try:
                    parts = pair.split(':')
                    if len(parts) == 2:
                        _ms_id = int(parts[0])
                        release_pct = float(parts[1])
                        total_release_pct += release_pct
                except (ValueError, TypeError):
                    continue

            # Release the proportional amount: if total_release_pct < 100,
            # we partially release. For simplicity, we release all held entries
            # proportionally.
            if total_release_pct > 0:
                # Get all held entries for this invoice
                cursor.execute("""
                    SELECT id, amount FROM officer_revenue_ledger
                    WHERE invoice_request_id = ? AND is_held = 1
                """, (request_id,))
                held_entries = cursor.fetchall()

                release_fraction = min(total_release_pct / 100.0, 1.0)

                for entry in held_entries:
                    if release_fraction >= 1.0:
                        # Full release
                        cursor.execute("""
                            UPDATE officer_revenue_ledger
                            SET is_held = 0,
                                released_by = ?,
                                released_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (user['officer_id'], entry['id']))
                    else:
                        # Partial release: reduce held amount and create released entry
                        original_amount = entry['amount']
                        released_amount = original_amount * release_fraction
                        remaining_held = original_amount - released_amount

                        # Update existing entry to the remaining held amount
                        cursor.execute("""
                            UPDATE officer_revenue_ledger
                            SET amount = ?,
                                is_held = 1
                            WHERE id = ?
                        """, (remaining_held, entry['id']))

                        # Create new entry for the released portion
                        cursor.execute("""
                            SELECT officer_id, assignment_id, invoice_request_id,
                                   share_percent, fy_period, transaction_date
                            FROM officer_revenue_ledger WHERE id = ?
                        """, (entry['id'],))
                        orig = dict(cursor.fetchone())

                        cursor.execute("""
                            INSERT INTO officer_revenue_ledger
                            (officer_id, assignment_id, invoice_request_id,
                             revenue_type, share_percent, amount, fy_period,
                             transaction_date, is_held, released_by, released_at,
                             remarks)
                            VALUES (?, ?, ?, 'INVOICE_80', ?, ?, ?, ?,
                                    0, ?, CURRENT_TIMESTAMP,
                                    'Partial release by TL')
                        """, (
                            orig['officer_id'],
                            orig['assignment_id'],
                            orig['invoice_request_id'],
                            orig['share_percent'],
                            released_amount,
                            orig['fy_period'],
                            orig['transaction_date'],
                            user['officer_id'],
                        ))
        else:
            # Full release of all held entries
            cursor.execute("""
                UPDATE officer_revenue_ledger
                SET is_held = 0,
                    released_by = ?,
                    released_at = CURRENT_TIMESTAMP
                WHERE invoice_request_id = ? AND is_held = 1
            """, (user['officer_id'], request_id))

        # Log the action
        cursor.execute("""
            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks)
            VALUES (?, 'RELEASE', 'invoice_request', ?,
                    'TL released revenue hold (Feature 4A)')
        """, (user['officer_id'], request_id))

    return RedirectResponse(
        url=f"/finance/invoice-request/{invoice_req['assignment_id']}?success=revenue_released",
        status_code=302
    )
