# PMS -- Low-Level Design (LLD)

## Module and File Breakdown

### Core Application (`app/`)

| File | Responsibility | Main Exports | Dependencies |
|------|---------------|--------------|--------------|
| `main.py` | FastAPI app creation, route registration, error handlers, startup event | `app` (FastAPI instance) | All route modules, `database`, `templates_config` |
| `config.py` | Environment loading, paths, constants, business config | `DATABASE_URL`, `SECRET_KEY`, `USE_POSTGRES`, `ASSIGNMENT_TYPES`, option lists | `os`, `dotenv` |
| `database.py` | DB schema (35+ tables), connection management, progress/revenue calculations | `get_db()`, `init_database()`, revenue functions, progress functions | `psycopg2`, `sqlite3`, `config` |
| `auth.py` | Password hashing, session CRUD, officer authentication, token serialization | `authenticate_officer()`, `create_session()`, `validate_session()`, `hash_password()` | `bcrypt`, `itsdangerous`, `database` |
| `roles.py` | 8-tier RBAC, permission checks, scope-based access, role hierarchy | `get_user_role()`, `has_permission()`, `is_admin()`, `is_head()`, `can_approve_in_office()` | `database` |
| `dependencies.py` | Route-level auth guards, permission wrappers | `get_current_user()`, `require_auth()`, `require_permission()`, `require_head_or_above()` | `auth`, `roles` |
| `templates_config.py` | Jinja2 setup, custom filters | `templates`, `format_date()`, `format_datetime()`, `safe_tojson()` | `jinja2` |

### Route Modules (`app/routes/`)

| File | Responsibility | Key Endpoints | Dependencies |
|------|---------------|---------------|--------------|
| `auth_routes.py` | Login/logout flow | `GET/POST /login`, `GET /logout` | `auth`, `dependencies` |
| `dashboard_routes.py` | Main dashboard, monthly API | `GET /dashboard`, `GET /api/monthly-breakdown` | `database`, `dependencies`, `roles` |
| `assignment_routes.py` | Assignment CRUD, milestones, expenditure | 18 endpoints under `/assignment` | `database`, `dependencies`, `config` |
| `approval_routes.py` | Multi-stage approval workflow | 22 endpoints under `/approvals` | `database`, `dependencies`, `roles` |
| `finance_routes.py` | Invoice requests, payments, 80-20 revenue | 7 endpoints under `/finance` | `database`, revenue functions |
| `revenue_routes.py` | Revenue share allocation | 4 endpoints under `/revenue` | `database`, `dependencies` |
| `mis_routes.py` | MIS analytics dashboards | 12 endpoints under `/mis` | `database`, `dependencies` |
| `admin_routes.py` | User/role/hierarchy management | 14 endpoints under `/admin` | `database`, `auth`, `roles` |
| `training_routes.py` | Training programme lifecycle | 20 endpoints under `/training` | `database`, `dependencies` |
| `change_request_routes.py` | Change request workflow | 7 endpoints under `/change-request` | `database`, `dependencies` |
| `non_revenue_routes.py` | Non-revenue suggestions | 8 endpoints under `/non-revenue` | `database`, `dependencies` |
| `data_routes.py` | Export/import, config CRUD | 7 endpoints under `/data` | `database`, `pandas`, `openpyxl` |
| `profile_routes.py` | Profile, password, role switch | 4 endpoints under `/profile` | `auth`, `dependencies` |

### Scripts (`scripts/`)

| File | Responsibility |
|------|---------------|
| `init_db.py` | Database initialization, table creation, default data |
| `setup_all.py` | Master setup: init DB + import officers + generate data + create admin |
| `import_officers.py` | Import officers from Excel |
| `generate_dummy_data.py` | Generate ~200 test assignments |
| `setup_roles.py` | Assign default roles based on designation |
| `create_admin.py` | Create system admin user |

---

## Function and Class Specifications

### `app/auth.py` -- Authentication

#### `hash_password(password: str) -> str`
- **Purpose:** Hash a plaintext password using bcrypt.
- **Inputs:** `password` -- plaintext string.
- **Outputs:** bcrypt hash string (UTF-8 encoded).
- **Side effects:** None.
- **Error handling:** None; bcrypt handles salt internally.

#### `verify_password(password: str, password_hash: str) -> bool`
- **Purpose:** Check if plaintext matches a bcrypt hash.
- **Inputs:** `password` -- plaintext; `password_hash` -- stored hash.
- **Outputs:** `True` if match, `False` otherwise.
- **Side effects:** None.
- **Error handling:** Returns `False` on any exception (malformed hash, etc.).

#### `authenticate_officer(email: str, password: str) -> Optional[dict]`
- **Purpose:** Authenticate an officer by email + password lookup.
- **Inputs:** `email` (case-insensitive); `password` (plaintext).
- **Outputs:** Dict `{officer_id, name, email, office_id, designation}` or `None`.
- **Side effects:** DB read on `officers` table.
- **Error handling:** Returns `None` if email not found, officer inactive, or password mismatch.
- **Business rules:** Email lookup is case-insensitive (`LOWER(email)`). Inactive officers cannot login.

#### `create_session(officer_id: str, active_role: str = None) -> str`
- **Purpose:** Create a new DB-backed session for an officer.
- **Inputs:** `officer_id`; optional `active_role`.
- **Outputs:** New session ID (32-byte URL-safe token).
- **Side effects:** Deletes existing sessions for this officer; inserts new row in `sessions` table with 24h expiry.
- **Business rules:** Only one active session per officer (previous sessions are deleted).

#### `validate_session(session_id: str) -> Optional[dict]`
- **Purpose:** Validate a session ID and return enriched user info.
- **Inputs:** `session_id` from cookie.
- **Outputs:** Full user dict with roles, permissions, display info -- or `None`.
- **Side effects:** Deletes expired sessions from DB.
- **Business rules:** Session must not be expired. Officer must be active. Roles are enriched from `officer_roles` table + legacy `admin_role_id`.

#### `serialize_session(session_id: str) -> str`
- **Purpose:** Sign a session ID for cookie storage.
- **Inputs:** `session_id`.
- **Outputs:** Signed token string.
- **Invariant:** Uses `SECRET_KEY` from config for HMAC signing.

#### `deserialize_session(token: str) -> Optional[str]`
- **Purpose:** Verify and extract session ID from signed cookie.
- **Inputs:** `token` from cookie.
- **Outputs:** Session ID or `None`.
- **Error handling:** Returns `None` on signature mismatch or age > `SESSION_MAX_AGE`.

### `app/roles.py` -- RBAC System

#### Constants

```python
ROLE_ADMIN = 'ADMIN'
ROLE_DG = 'DG'
ROLE_DDG_I = 'DDG-I'
ROLE_DDG_II = 'DDG-II'
ROLE_RD_HEAD = 'RD_HEAD'
ROLE_GROUP_HEAD = 'GROUP_HEAD'
ROLE_TEAM_LEADER = 'TEAM_LEADER'
ROLE_OFFICER = 'OFFICER'

ROLE_HIERARCHY = [ADMIN, DG, DDG_I, DDG_II, RD_HEAD, GROUP_HEAD, TEAM_LEADER, OFFICER]

ROLE_PERMISSIONS = {
    ROLE_ADMIN: ['view_all_mis', 'export_data', 'import_data', 'manage_config', 'manage_users', ...],
    ROLE_RD_HEAD: ['view_all_mis', 'allocate_team_leader', 'approve_assignment', ...],
    ROLE_TEAM_LEADER: ['view_all_mis', 'set_team', 'fill_assignment_details', ...],
    ROLE_OFFICER: ['view_all_mis', 'register_assignment', 'raise_request'],
    ...
}
```

#### `get_user_roles(user: dict) -> list[dict]`
- **Purpose:** Get all roles for a user, merged from `officer_roles` table and legacy fields.
- **Inputs:** User dict (must contain `officer_id`).
- **Outputs:** List of `{role_type, scope_type, scope_value, is_primary}` dicts, sorted by hierarchy.
- **Side effects:** DB read on `officer_roles`, `assignments` (for TL check), `reporting_hierarchy`.
- **Business rules:** Always includes OFFICER as base role. TL role inferred from `assignments.team_leader_officer_id`.

#### `has_permission(user: dict, permission: str) -> bool`
- **Purpose:** Check if user has a specific permission.
- **Inputs:** User dict; permission string (e.g., `'approve_assignment'`).
- **Outputs:** Boolean.
- **Business rules:** Permissions aggregate across all roles. Admin has all permissions.

#### `can_approve_in_office(user: dict, office_id: str) -> bool`
- **Purpose:** Check if user can approve items in a specific office.
- **Inputs:** User dict; `office_id`.
- **Outputs:** Boolean.
- **Business rules:** Admin/DG/DDG can approve anywhere. RD_HEAD only for their office. GROUP_HEAD for offices in their group.

#### `is_rd_head_for(user: dict, office_id: str) -> bool`
- **Purpose:** Check if user is RD Head specifically for the given office.
- **Inputs:** User dict; `office_id`.
- **Outputs:** Boolean.

#### `get_reporting_ddg(entity_type: str, entity_value: str) -> str`
- **Purpose:** Look up which DDG an office/group reports to.
- **Inputs:** `entity_type` ('OFFICE' or 'GROUP'); `entity_value` (office_id or group_code).
- **Outputs:** DDG role string ('DDG-I' or 'DDG-II') or `None`.
- **Side effects:** DB read on `reporting_hierarchy`.

### `app/dependencies.py` -- Route Guards

#### `get_current_user(request: Request) -> Optional[dict]`
- **Purpose:** Extract user from session cookie on every request.
- **Inputs:** FastAPI `Request`.
- **Outputs:** User dict or `None`.
- **Flow:** Cookie -> `deserialize_session()` -> `validate_session()`.

#### `require_permission(request, permission) -> tuple[Optional[dict], Optional[RedirectResponse]]`
- **Purpose:** Gate a route on a specific permission.
- **Inputs:** Request; permission string.
- **Outputs:** `(user, None)` if authorized; `(None, redirect)` if not.
- **Business rules:** Redirects to `/login` if unauthenticated; `/dashboard?error=unauthorized` if no permission.

#### `require_head_or_above(request) -> tuple[Optional[dict], Optional[RedirectResponse]]`
- **Purpose:** Gate a route to Head, DDG, DG, or Admin roles.
- **Business rules:** Same redirect pattern as `require_permission`.

### `app/database.py` -- Database Layer

#### `get_db() -> ContextManager[connection]`
- **Purpose:** Context manager yielding a DB connection with auto-commit/rollback.
- **Outputs:** Connection object with cursor support.
- **Side effects:** Opens connection; commits on success; rolls back on exception; always closes.
- **Invariant:** PostgreSQL connections use `PostgresCursorWrapper` for DictRow compatibility.

#### `init_database()`
- **Purpose:** Create all tables, add missing columns (ALTER TABLE), insert defaults.
- **Side effects:** Creates 35+ tables if not exist; inserts expenditure heads, config options, groups, hierarchy, admin user.
- **Error handling:** Each ALTER TABLE is wrapped in try/except to handle existing columns.

#### `calculate_physical_progress(assignment_id: int) -> float`
- **Purpose:** Calculate weighted physical progress based on milestone invoicing.
- **Business rules:** Each milestone weighted by `invoice_percent`. Score: 100% if payment received, 80% if invoiced, 0% otherwise. Returns 0-100 scale.

#### `calculate_timeline_progress(assignment_id: int) -> float`
- **Purpose:** Calculate timeline progress based on milestone completion vs. target dates.
- **Business rules:** Completed on/before target = 100%. Delayed = reduced score (min 50%). Not started but past due = 50%.

#### `allocate_officer_revenue_80(invoice_request_id: int)`
- **Purpose:** Distribute 80% of invoice revenue to officers based on their share percentages.
- **Side effects:** Inserts rows into `officer_revenue_ledger` with `revenue_type='INVOICE_80'`.
- **Business rules:** Each officer gets `share_percent / 100 * revenue_recognized_80`.

#### `allocate_officer_revenue_20(payment_receipt_id: int)`
- **Purpose:** Distribute remaining 20% of payment to officers based on share percentages.
- **Side effects:** Inserts rows into `officer_revenue_ledger` with `revenue_type='PAYMENT_20'`.

#### `get_current_fy() -> str`
- **Purpose:** Get current financial year (April-March) in format `'2024-25'`.
- **Business rules:** If month >= April, FY = current_year - next_year. If month < April, FY = prev_year - current_year.

### `app/routes/approval_routes.py` -- Workflow Engine

#### `require_approver_access(request) -> tuple[Optional[dict], Optional[RedirectResponse]]`
- **Purpose:** Check if user can access approval actions (Head, DDG, DG, or Admin).
- **Business rules:** Redirects non-approvers to dashboard.

#### `_approvals_page_inner(request, user) -> TemplateResponse`
- **Purpose:** Build the approvals dashboard with all pending items across all categories.
- **Side effects:** 15+ DB queries for pending registrations, TL assignments, section approvals, change requests, training, etc.

#### `_check_all_sections_approved(cursor, assignment_id, ph)`
- **Purpose:** After any section approval, check if all 5 are approved -> auto-activate.
- **Business rules:** All of `approval_status`, `cost_approval_status`, `team_approval_status`, `milestone_approval_status`, `revenue_approval_status` must be `'APPROVED'`. Sets `workflow_stage='ACTIVE'`, `status='Ongoing'`.
- **Invariant:** Only triggers if current `workflow_stage` is `'DETAIL_ENTRY'`.

#### Section Submit Routes (`/cost/{id}/submit`, `/team/{id}/submit`, etc.)
- **Business rules:** Only TL of the assignment (or head/admin) can submit. Cost requires expenditure_items > 0. Milestone requires milestones > 0. Revenue requires revenue_shares > 0.

#### Section Approve Routes (`/cost/{id}/approve`, `/team/{id}/approve`, etc.)
- **Business rules:** Only approvers (head/DDG/DG/admin) can approve. Each approval calls `_check_all_sections_approved()`.

### `app/routes/assignment_routes.py` -- Assignment CRUD

#### `register(request) -> POST`
- **Purpose:** Register a new activity with minimal info.
- **Inputs:** `title`, `type` (ASSIGNMENT/TRAINING/DEVELOPMENT), `client`, `description`.
- **Side effects:** INSERT into `assignments`, INSERT into `approval_requests`, INSERT into `activity_log`.
- **Business rules:** Auto-generates `assignment_no` as `NPC/OFFICE/TYPE_PREFIX/SEQ/FY`. Sets `registration_status='PENDING_APPROVAL'`, `workflow_stage='REGISTRATION'`.

#### `edit_assignment_submit(request, assignment_id) -> POST`
- **Purpose:** Save detailed assignment info (type-specific fields).
- **Inputs:** Form fields varying by type (ASSIGNMENT: tor_scope, client_type, etc.; TRAINING: venue, faculty, etc.; DEVELOPMENT: man_days).
- **Side effects:** UPDATE `assignments`, reset `approval_status` to `'SUBMITTED'` if previously approved.
- **Business rules:** Development work: `total_value = man_days * 0.20` (Lakhs), `is_notional = 1`.

---

## Domain Model Details

### Activity Types
- **ASSIGNMENT**: Client-facing project work with billing (ToR, work order, invoices).
- **TRAINING**: Training programmes with venues, participants, faculty.
- **DEVELOPMENT**: Non-revenue internal work with notional value (man-days * Rs.20k/day).

### Workflow Stages
```
REGISTRATION -> TL_ASSIGNMENT -> DETAIL_ENTRY -> ACTIVE -> COMPLETED
```

### Approval Statuses (per section)
```
DRAFT -> SUBMITTED -> APPROVED (or REJECTED -> SUBMITTED again)
```

### Registration Statuses
```
PENDING_APPROVAL -> APPROVED (or REJECTED)
```

### Assignment Statuses (operational)
```
Not Started | Pipeline | Ongoing | Completed | On Hold | Cancelled
```

### Revenue Model (80-20)
- On **invoice approval**: 80% of invoice amount recognized as revenue, allocated to officers by share %.
- On **payment receipt**: remaining 20% of payment recognized, allocated to officers by share %.
- Tracked in `officer_revenue_ledger` with `revenue_type = 'INVOICE_80' | 'PAYMENT_20'`.

### Permission Model
- Roles are hierarchical: higher roles inherit lower role capabilities (in practice, through explicit permission lists).
- Scoped roles: RD_HEAD sees only their office; GROUP_HEAD sees their group's offices; DDG/DG/Admin see everything.
- TL role is inferred from `assignments.team_leader_officer_id` -- not explicitly assigned in `officer_roles`.

---

## Internal Flows

### Flow: Register Activity -> Active

1. **Officer** calls `POST /assignment/register` with `{title, type, client}`.
2. `assignment_routes.register()` generates `assignment_no`, inserts into `assignments` with `workflow_stage='REGISTRATION'`, `registration_status='PENDING_APPROVAL'`.
3. Creates `approval_requests` record of `type='REGISTRATION'`.
4. **Head** visits `GET /approvals` -> `approval_routes.approvals_page()` queries `assignments WHERE registration_status='PENDING_APPROVAL'`.
5. **Head** calls `POST /approvals/registration/{id}/approve` -> updates `registration_status='APPROVED'`, `workflow_stage='TL_ASSIGNMENT'`.
6. **Head** calls `POST /approvals/allocate-tl/{id}` with `team_leader_id` -> updates `team_leader_officer_id`, `workflow_stage='DETAIL_ENTRY'`.
7. **TL** visits `GET /assignment/edit/{id}` -> `assignment_routes.edit_assignment()` routes to type-specific template.
8. **TL** submits details via `POST /assignment/edit/{id}` -> `edit_assignment_submit()` updates type-specific columns, sets `details_filled=1`.
9. **TL** submits each section: `POST /approvals/{section}/{id}/submit` (cost, team, milestone, revenue).
10. **Head** approves each: `POST /approvals/{section}/{id}/approve` -> `_check_all_sections_approved()`.
11. When all 5 sections approved: auto-sets `workflow_stage='ACTIVE'`, `status='Ongoing'`.

### Flow: Invoice -> 80-20 Revenue

1. **TL/Officer** creates invoice request: `POST /finance/invoice-request/{id}` with `{milestone_id, invoice_type, invoice_amount}`.
2. `finance_routes.submit_invoice_request()` inserts into `invoice_requests` with `status='PENDING'`.
3. **Head/Finance** approves: `POST /finance/invoice/{id}/approve`.
4. `approve_invoice()` updates `status='APPROVED'`, calculates `revenue_recognized_80 = amount * 0.80`.
5. Calls `allocate_officer_revenue_80(invoice_id)` -> queries `revenue_shares` for the assignment -> inserts into `officer_revenue_ledger` with proportional amounts.
6. Updates milestone `invoice_raised=1`.
7. Later, **Finance** records payment: `POST /finance/payment/{id}`.
8. `record_payment()` inserts `payment_receipts`, calculates `revenue_recognized_20 = amount * 0.20`.
9. Calls `allocate_officer_revenue_20(payment_id)` -> same proportional allocation to `officer_revenue_ledger`.

### Flow: Change Request Escalation

1. **Officer** submits: `POST /change-request/new/{assignment_id}` with `{change_type, description}`.
2. Creates `approval_requests` with `request_type='CHANGE_REQUEST'`, `review_status='PENDING'`.
3. **TL** reviews: `GET /change-request/review/{id}` -> either forwards or rejects.
4. If forwarded: `POST /change-request/review/{id}/forward` -> sets `review_status='FORWARDED'`.
5. **Head** approves: `POST /change-request/{id}/approve` -> sets `status='APPROVED'`.

---

## Testing Strategy (Design Perspective)

### Unit Tests

| Module | What to Test | Risk Level |
|--------|-------------|------------|
| `auth.py` | Password hash/verify, session create/validate/delete, token serialize/deserialize | **High** -- security critical |
| `roles.py` | Every role check function, permission aggregation, scope validation, hierarchy ordering | **High** -- access control |
| `dependencies.py` | Auth guard functions with mocked requests | **Medium** |
| `config.py` | Environment loading, constant values | **Low** |
| `templates_config.py` | Date formatting, JSON serialization | **Low** |
| `database.py` | Progress calculations, revenue allocation logic, FY calculation, number generation | **High** -- financial accuracy |

### Integration Tests

| Boundary | What to Test |
|----------|-------------|
| Auth routes + DB | Login with valid/invalid credentials, session creation, logout |
| Assignment routes + DB | Register, edit, view with real DB operations |
| Approval routes + DB | Full approval workflow through all stages |
| Finance routes + DB | Invoice creation, approval, 80-20 allocation correctness |
| Admin routes + DB | Role assignment, user management |
| Revenue routes + DB | Share allocation, percentage validation (must sum to 100%) |

### E2E Tests

| Journey | Steps |
|---------|-------|
| Registration workflow | Login -> Register activity -> Head approves -> TL assigned -> Fill details -> Submit sections -> Approve all -> Verify ACTIVE |
| Invoice workflow | Login -> Create invoice -> Approve -> Record payment -> Verify revenue ledger |
| Permission boundaries | Login as Officer -> Verify cannot access admin pages -> Verify cannot approve |

### High-Risk Areas Needing Extra Test Coverage
1. **80-20 revenue allocation** -- financial calculations must be exact.
2. **Auto-activation logic** -- `_check_all_sections_approved()` must only fire when all 5 are truly approved.
3. **Role permission checks** -- every route must enforce correct access.
4. **Session security** -- expired sessions must be rejected, token tampering must fail.
5. **Dual-DB compatibility** -- all queries must work on both SQLite and PostgreSQL.

---

## Refactoring / Change Rules

### SAFE Changes (Low Risk)
- Adding new HTML templates.
- Adding new config options to `config_options` table.
- Adding new columns to existing tables (with ALTER TABLE + default).
- Adding new MIS dashboard views (read-only queries).
- Modifying CSS/static assets.

**Required tests:** Unit tests for new logic; verify no template rendering errors.

### DANGEROUS Changes (High Risk)
- Modifying `auth.py` (session handling, password verification).
- Changing `roles.py` (permission maps, hierarchy order).
- Altering `database.py` schema or revenue calculation functions.
- Changing approval workflow logic in `approval_routes.py`.
- Modifying finance routes (80-20 model).
- Changing `dependencies.py` guard functions.

**Required tests:** Full unit test suite + integration tests for affected routes + E2E workflow tests. Always run the complete test suite before merging.

### Column/Schema Changes
- **Never** remove columns -- only add with defaults.
- **Always** wrap ALTER TABLE in try/except for idempotency.
- **Always** test with both SQLite and PostgreSQL.
