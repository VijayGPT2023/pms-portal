# CLAUDE.md -- AI-Assisted Development Guidelines for PMS Portal

## Tech Stack (Django 6.0.3 — migrated from FastAPI on 2026-03-31)

| Layer | Technology |
|-------|-----------|
| Backend | Django 6.0.3 (Python 3.12) |
| Database | SQLite (dev) + PostgreSQL (prod) via Django ORM |
| Templates | Django Templates + HTMX 2.0.4 + Alpine.js 3.14 |
| CSS | Custom CSS (3,580 lines) — self-hosted |
| Charts | Chart.js 4.4.7 (self-hosted) |
| Auth | Django built-in sessions + custom Officer model |
| RBAC | 8-tier role hierarchy via OfficerRole model |
| State Machine | django-fsm on Assignment + InvoiceRequest models |
| Audit | django-auditlog (10 models auto-tracked) |
| Static Files | WhiteNoise (self-hosted, GIGW 3.0 compliant) |
| Testing | pytest + pytest-django (96 tests) |

## Before Making Any Change

1. **Read `docs/HLD.md`** to understand the system architecture.
2. **Read `docs/LLD.md`** to understand function signatures and domain rules.
3. **Identify which module(s)** your change touches.

## Project Structure (Django)

```
pms_portal/              -- Django project settings
  settings.py            -- Configuration (dual-DB, auth, business rules)
  urls.py                -- Root URL config

core/                    -- Main Django app
  models.py              -- 37 ORM models (replaces 14,500 lines of raw SQL)
  admin.py               -- Auto-generated admin panel (37 models registered)
  urls.py                -- 177+ URL patterns
  backends.py            -- Email-based auth backend
  context_processors.py  -- Global template context
  views/                 -- 20 view modules
    main.py              -- Auth, health check
    dashboard.py         -- Dashboard + APIs
    assignments.py       -- Assignment CRUD + workflow
    approvals.py         -- 23 approval endpoints
    finance.py           -- Invoicing, payments, 80-20 revenue
    mis.py               -- MIS Command Center (6 tabs)
    training.py          -- Training programme lifecycle
    utilization.py       -- Utilization claims workflow
    reports.py           -- Delay, physical, financial reports
    clients.py           -- Client database
    revenue.py           -- Revenue share allocation
    admin_views.py       -- User/role management
    data_management.py   -- Import/export, config
    non_revenue.py       -- Development work
    proposals.py         -- Document upload/download
    profile.py           -- User profile, password
    change_requests.py   -- Change request workflow
  templates/             -- 55 Django templates
    base.html            -- Master layout with sidebar
    login.html           -- Login page
    assignments/         -- 10 assignment templates
    approvals/           -- Approval hub
    finance/             -- Finance templates
    (... 14 subdirectories)
  static/
    css/style.css         -- Main stylesheet
    css/fonts.css         -- Self-hosted Inter font
    js/htmx.min.js        -- HTMX (self-hosted)
    js/alpine.min.js      -- Alpine.js (self-hosted)
    js/chart.min.js       -- Chart.js (self-hosted)

tests_django/            -- Django test suite (96 tests)
  unit/test_models.py    -- 31 model + state machine tests
  integration/           -- 65 route tests

scripts/
  seed_django.py         -- API-based seed data (not raw SQL)

run-uat.sh               -- Automated UAT script (40+ endpoint tests)
```

## Test Commands

```bash
# All tests (96 tests, ~3 minutes)
python -m pytest tests_django/ -v

# Unit tests only (31 tests, fast)
python -m pytest tests_django/unit/ -v

# Integration tests only (65 tests)
python -m pytest tests_django/integration/ -v

# With coverage
python -m pytest tests_django/ --cov=core --cov-report=term-missing

# Seed data
python scripts/seed_django.py

# UAT (requires running server)
bash run-uat.sh http://localhost:8000

# Run server
python manage.py runserver 0.0.0.0:8000
```

## Key Technical Rules

### Database
- **Django ORM only** — no raw SQL. Use `Model.objects.filter()`, `annotate()`, `aggregate()`.
- **Migrations are auto-generated**: `python manage.py makemigrations` then `python manage.py migrate`.
- **Never modify a deployed migration** — create a new one.
- **Custom FK fields** use `to_field="officer_id"` — assign model instances, not strings.

### Authentication & Authorization
- Every view must use `@login_required` decorator.
- Custom auth backend in `core/backends.py` — login via email.
- RBAC: Check `request.user.admin_role_id` or query `OfficerRole` model.
- Session cookies are HTTPOnly, SameSite=Lax (Django built-in).

### Workflow (django-fsm)
- **5 workflow stages**: REGISTRATION -> TL_ASSIGNMENT -> DETAIL_ENTRY -> ACTIVE -> COMPLETED.
- **5 independent section approvals**: approval_status, cost, team, milestone, revenue.
- **Transitions are methods**: `assignment.submit_registration()`, `assignment.approve_registration()`.
- **Auto-activation**: `assignment.try_auto_activate()` when all 5 sections approved.
- **TransitionNotAllowed** exception if invalid transition attempted.

### Revenue Model (80-20)
- `InvoiceRequest.approve()` sets `revenue_recognized_80 = amount * 0.80`.
- `PaymentReceipt.save()` sets `revenue_recognized_20 = amount * 0.20`.
- Both allocated to officers by their share percentages in `OfficerRevenueLedger`.

### Templates
- All templates extend `base.html` with `{% extends "base.html" %}`.
- Use `{% url 'core:name' %}` for links, `{% static 'path' %}` for assets.
- Use `{% csrf_token %}` in all forms.
- HTMX for dynamic updates: `hx-get`, `hx-post`, `hx-target`.

## What is Safe vs Dangerous to Change

### SAFE (low risk):
- Adding new templates
- Adding new views (with URL patterns)
- Adding new model fields (with migration)
- CSS changes
- Template content changes

### DANGEROUS (high risk, run full test suite):
- `models.py` — especially Assignment model, FK relationships
- `approvals.py` — workflow state transitions
- `finance.py` — 80-20 revenue calculations
- `settings.py` — auth backends, middleware
- `urls.py` — URL pattern changes can break links

## Adding a New Feature

1. Add model fields in `core/models.py` if needed
2. Run `python manage.py makemigrations core && python manage.py migrate`
3. Add views in `core/views/module.py`
4. Add URL patterns in `core/urls.py`
5. Create templates in `core/templates/module/`
6. Register in admin in `core/admin.py`
7. Add tests in `tests_django/`
8. Run `python -m pytest tests_django/ -v`
