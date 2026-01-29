# CLAUDE.md -- AI-Assisted Development Guidelines for PMS Portal

## Before Making Any Change

1. **Read `docs/HLD.md`** to understand the system architecture, component boundaries, and data flows.
2. **Read `docs/LLD.md`** to understand function signatures, domain rules, and internal flows.
3. **Identify which module(s)** your change touches. Refer to the Module Breakdown in LLD.md.

## Development Workflow

### For any new feature or refactor:

1. **Write/update tests first** (test-driven approach):
   - Unit tests in `tests/unit/` for pure logic and business rules.
   - Integration tests in `tests/integration/` if the change touches routes, DB, or cross-module boundaries.
   - E2E tests in `tests/e2e/` if the change affects user-visible flows.

2. **Then modify code** to satisfy the tests.

3. **After code changes:**
   - Run the full test suite: `pytest tests/unit/ tests/integration/ -v`
   - If any test fails, fix code or tests until green.
   - Never push with failing tests.

4. **If architecture or behavior changes:**
   - Update `docs/HLD.md` if components, data flows, or APIs changed.
   - Update `docs/LLD.md` if function signatures, domain rules, or internal flows changed.

## Project Structure

```
app/
  main.py              -- FastAPI app, route registration
  config.py            -- Environment, constants
  database.py          -- Schema (35+ tables), connection, revenue/progress functions
  auth.py              -- Password hashing, sessions, authentication
  roles.py             -- 8-tier RBAC, permissions
  dependencies.py      -- Route auth guards
  templates_config.py  -- Jinja2 setup, filters
  routes/              -- 14 route modules (~129 endpoints)
  templates/           -- 48 Jinja2 HTML templates
  static/css/          -- Stylesheets

tests/
  unit/                -- Fast, isolated tests (mock DB/externals)
  integration/         -- Tests with real SQLite test DB
  e2e/                 -- Full server tests with HTTP requests
  __mocks__/           -- Shared fixtures and mock data
```

## Test Commands

```bash
# Unit tests only (fast)
pytest tests/unit/ -m unit -v

# Integration tests (uses SQLite test DB)
pytest tests/integration/ -m integration -v

# E2E tests (starts a test server)
pytest tests/e2e/ -m e2e -v

# All tests
pytest -v

# With coverage
pytest tests/unit/ tests/integration/ --cov=app --cov-report=term-missing
```

## Key Technical Rules

### Database
- **Dual DB support**: All queries must work on both SQLite (`?` placeholders) and PostgreSQL (`%s`).
- **Never DROP columns** -- only ADD COLUMN with defaults.
- **Wrap ALTER TABLE** in try/except for idempotency.
- **Use `get_db()` context manager** for all DB access (auto-commit/rollback).

### Authentication & Authorization
- Every route must check authentication via `get_current_user(request)`.
- Use `require_permission()`, `require_head_or_above()`, or `require_admin()` for access control.
- Session cookies are HTTPOnly, SameSite=Lax.

### Workflow
- **5 workflow stages**: REGISTRATION -> TL_ASSIGNMENT -> DETAIL_ENTRY -> ACTIVE -> COMPLETED.
- **5 independent section approvals**: approval_status, cost, team, milestone, revenue.
- **Auto-activation**: When all 5 sections are APPROVED and stage is DETAIL_ENTRY, auto-set to ACTIVE.
- **Reset-on-edit**: Editing a section after approval resets its status to SUBMITTED.

### Revenue Model (80-20)
- 80% of invoice amount recognized on invoice approval.
- 20% of payment amount recognized on payment receipt.
- Both allocated to officers by their share percentages.

## What is Safe vs Dangerous to Change

### SAFE (low risk):
- Adding new HTML templates
- Adding new config options
- Adding new DB columns (with ALTER TABLE + default)
- Adding new MIS views (read-only queries)
- CSS changes

### DANGEROUS (high risk, run full test suite):
- `auth.py` -- session/password logic
- `roles.py` -- permission maps, hierarchy
- `database.py` -- schema changes, revenue calculations
- `approval_routes.py` -- workflow state transitions
- `finance_routes.py` -- 80-20 revenue model
- `dependencies.py` -- auth guard functions

## Adding a New Route Module

1. Create `app/routes/new_module_routes.py`
2. Define `router = APIRouter()`
3. Register in `app/main.py`: `app.include_router(router, prefix="/new-module")`
4. Add auth checks on every endpoint
5. Create templates in `app/templates/`
6. Add unit tests in `tests/unit/test_new_module.py`
7. Add integration tests in `tests/integration/test_new_module_routes.py`
8. Update `docs/HLD.md` (component list, API table) and `docs/LLD.md` (file breakdown)
