"""
Shared test fixtures -- mock data for unit and integration tests.
"""
import datetime


# ── Officer / User fixtures ──────────────────────────────────────────

def make_officer(
    officer_id="OFF001",
    name="Test Officer",
    email="test@npcindia.gov.in",
    office_id="HQ",
    designation="Consultant",
    is_active=1,
    password_hash=None,
    admin_role_id=None,
):
    return {
        "officer_id": officer_id,
        "name": name,
        "email": email,
        "office_id": office_id,
        "designation": designation,
        "is_active": is_active,
        "password_hash": password_hash,
        "admin_role_id": admin_role_id,
    }


def make_user(
    officer_id="OFF001",
    name="Test Officer",
    email="test@npcindia.gov.in",
    office_id="HQ",
    designation="Consultant",
    role="OFFICER",
    roles=None,
    permissions=None,
    active_role=None,
    is_admin=False,
    admin_role_id=None,
):
    """Build a user dict as returned by validate_session()."""
    return {
        "officer_id": officer_id,
        "name": name,
        "email": email,
        "office_id": office_id,
        "designation": designation,
        "role": role,
        "roles": roles or [{"role_type": role, "scope_type": "INDIVIDUAL", "scope_value": None}],
        "permissions": permissions or ["view_all_mis", "register_assignment", "raise_request"],
        "active_role": active_role or role,
        "is_admin": is_admin,
        "admin_role_id": admin_role_id,
        "role_display": role,
    }


ADMIN_USER = make_user(
    officer_id="ADMIN",
    name="System Administrator",
    email="admin@npcindia.gov.in",
    role="ADMIN",
    is_admin=True,
    admin_role_id="ADMIN",
    permissions=[
        "view_all_mis", "export_data", "import_data", "manage_config",
        "manage_users", "reset_password", "change_roles", "download_reports",
    ],
)

DG_USER = make_user(
    officer_id="DG001",
    name="Director General",
    email="dg@npcindia.gov.in",
    role="DG",
    admin_role_id="DG",
    permissions=["view_all_mis", "approve_escalated", "download_reports"],
)

DDG_USER = make_user(
    officer_id="DDG001",
    name="Deputy DG-I",
    email="ddg1@npcindia.gov.in",
    role="DDG-I",
    admin_role_id="DDG-I",
    permissions=["view_all_mis", "approve_escalated", "download_reports"],
)

RD_HEAD_USER = make_user(
    officer_id="RD001",
    name="Regional Director",
    email="rd@npcindia.gov.in",
    office_id="RDDEL",
    role="RD_HEAD",
    admin_role_id="RD_HEAD",
    roles=[{"role_type": "RD_HEAD", "scope_type": "OFFICE", "scope_value": "RDDEL"}],
    permissions=[
        "view_all_mis", "allocate_team_leader", "approve_assignment",
        "approve_milestone", "approve_revenue_share", "download_reports",
    ],
)

GROUP_HEAD_USER = make_user(
    officer_id="GH001",
    name="Group Head",
    email="gh@npcindia.gov.in",
    role="GROUP_HEAD",
    admin_role_id="GROUP_HEAD",
    roles=[{"role_type": "GROUP_HEAD", "scope_type": "GROUP", "scope_value": "ES"}],
    permissions=[
        "view_all_mis", "allocate_team_leader", "approve_assignment",
        "approve_milestone", "approve_revenue_share", "download_reports",
    ],
)

TL_USER = make_user(
    officer_id="TL001",
    name="Team Leader",
    email="tl@npcindia.gov.in",
    role="TEAM_LEADER",
    admin_role_id="TEAM_LEADER",
    permissions=[
        "view_all_mis", "set_team", "fill_assignment_details",
        "fill_milestone_details", "download_reports",
    ],
)

OFFICER_USER = make_user(
    officer_id="OFF001",
    name="Test Officer",
    email="officer@npcindia.gov.in",
    role="OFFICER",
    permissions=["view_all_mis", "register_assignment", "raise_request"],
)


# ── Assignment fixtures ──────────────────────────────────────────────

def make_assignment(
    id=1,
    assignment_no="NPC/HQ/ES/P01/2025-26",
    type="ASSIGNMENT",
    title="Test Assignment",
    client="Test Corp",
    office_id="HQ",
    status="Pipeline",
    workflow_stage="REGISTRATION",
    registration_status="PENDING_APPROVAL",
    approval_status="DRAFT",
    cost_approval_status="DRAFT",
    team_approval_status="DRAFT",
    milestone_approval_status="DRAFT",
    revenue_approval_status="DRAFT",
    team_leader_officer_id=None,
    total_value=10.0,
    registered_by="OFF001",
    details_filled=0,
    **kwargs,
):
    base = {
        "id": id,
        "assignment_no": assignment_no,
        "type": type,
        "title": title,
        "client": client,
        "office_id": office_id,
        "status": status,
        "workflow_stage": workflow_stage,
        "registration_status": registration_status,
        "approval_status": approval_status,
        "cost_approval_status": cost_approval_status,
        "team_approval_status": team_approval_status,
        "milestone_approval_status": milestone_approval_status,
        "revenue_approval_status": revenue_approval_status,
        "team_leader_officer_id": team_leader_officer_id,
        "total_value": total_value,
        "registered_by": registered_by,
        "details_filled": details_filled,
        "tor_scope": None,
        "client_type": None,
        "city": None,
        "domain": None,
        "start_date": None,
        "target_date": None,
        "man_days": 0,
        "daily_rate": 0.20,
        "is_notional": 0,
        "gross_value": total_value,
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now(),
    }
    base.update(kwargs)
    return base


def make_milestone(
    id=1,
    assignment_id=1,
    milestone_no=1,
    title="Milestone 1",
    target_date="2025-06-30",
    status="Pending",
    invoice_percent=50.0,
    invoice_amount=5.0,
    invoice_raised=0,
    payment_received=0,
    revenue_percent=50.0,
    approval_status="PENDING",
    **kwargs,
):
    base = {
        "id": id,
        "assignment_id": assignment_id,
        "milestone_no": milestone_no,
        "title": title,
        "target_date": target_date,
        "status": status,
        "invoice_percent": invoice_percent,
        "invoice_amount": invoice_amount,
        "invoice_raised": invoice_raised,
        "payment_received": payment_received,
        "revenue_percent": revenue_percent,
        "approval_status": approval_status,
    }
    base.update(kwargs)
    return base


def make_revenue_share(
    id=1,
    assignment_id=1,
    officer_id="OFF001",
    share_percent=50.0,
    share_amount=5.0,
):
    return {
        "id": id,
        "assignment_id": assignment_id,
        "officer_id": officer_id,
        "share_percent": share_percent,
        "share_amount": share_amount,
    }


def make_invoice_request(
    id=1,
    request_number="INV-REQ/2025/000001",
    assignment_id=1,
    milestone_id=1,
    invoice_type="ADVANCE",
    invoice_amount=5.0,
    status="PENDING",
    requested_by="OFF001",
    revenue_recognized_80=4.0,
    fy_period="2025-26",
):
    return {
        "id": id,
        "request_number": request_number,
        "assignment_id": assignment_id,
        "milestone_id": milestone_id,
        "invoice_type": invoice_type,
        "invoice_amount": invoice_amount,
        "status": status,
        "requested_by": requested_by,
        "revenue_recognized_80": revenue_recognized_80,
        "fy_period": fy_period,
    }


def make_payment_receipt(
    id=1,
    receipt_number="RCPT/2025/000001",
    invoice_request_id=1,
    amount_received=5.0,
    payment_mode="NEFT",
    revenue_recognized_20=1.0,
    fy_period="2025-26",
):
    return {
        "id": id,
        "receipt_number": receipt_number,
        "invoice_request_id": invoice_request_id,
        "amount_received": amount_received,
        "payment_mode": payment_mode,
        "revenue_recognized_20": revenue_recognized_20,
        "fy_period": fy_period,
    }
