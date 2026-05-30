# Stub Pages Audit & Port Plan

> **COMPLETE (2026-05-31):** ALL stub pages ported. Cleanup (`91a8b53`),
> Tier-1 (`4e9a6e1`,`a971e16`,`55b912c`,`d0cb4d0`), Tier-2+3 (`568028b`).
> 32 pages → real UI. `TestNoStubsRemain` sweep confirms 0 placeholders remain.
> 264 tests green. No model/migration changes in the whole port effort.

**Date:** 2026-05-30
**Trigger:** UAT on pms.npcindia.info showed ~36 pages displaying
"This page is being ported from FastAPI to Django. Content coming soon."

---

## 1. Headline finding (good news)

The "coming soon" pages are **stub templates only**. The **view logic behind them is
fully ported and working** — it already runs queries and passes real context to the
template, which then ignores it and shows the placeholder.

Evidence:
- `finance.py` = 967 lines / 19 views · `training.py` = 655 / 29 · `utilization.py` = 354 / 16 ·
  `proposals.py` = 317 / 10 · `clients.py` = 255 / 11 · `reports.py` = 388 / 6 · `admin_views.py` = 340 / 8.
- Every priority view passes a full context dict (verified) — e.g.
  `finance_dashboard` → `{pending_invoices, approved_invoices, stats}`,
  `client_list` → `{clients, filter_*, client_types}`,
  `user_management_page` → `{officers, offices, roles, filter_*, search}`.

**Implication:** porting each page = writing one HTML template against an already-working
view. No model changes, no migrations, no new URLs. Low risk, no DB impact.

**Also note:** the red console errors seen in UAT (`Permissions-Policy: ambient-light-sensor`,
`enable_copy.js`, `Grammarly-check.js`) are **browser-extension noise, not portal errors**.

---

## 2. What works today (do not touch)

Dashboard · Register Activity · **Pre-WO Pipeline (G.2)** · **Development Work / Non-Revenue (G.3)** ·
**Edit Requests (G.1)** · **Pre-WO / Revenue / Non-Revenue MIS (Phase 3)** · login · static legal pages.

---

## 3. The 36 stub templates — context already available

### Tier 1 — Priority — ✅ DONE (committed, tested)

| # | Page | Template | View context already passed | Effort |
|---|---|---|---|---|
| 1 | Training list | `training/list.html` | `programmes, stats` | 0.5d |
| 2 | Training create/edit form | `training/form.html` | `programme, offices, officers, is_new` | 0.5d |
| 3 | Trainer allocation | `training/trainer_allocation.html` | (view ported) | 0.5d |
| 4 | Finance dashboard | `finance/finance_dashboard.html` | `pending_invoices, approved_invoices, stats` | 0.5d |
| 5 | Invoice request form | `finance/invoice_request_form.html` | `assignment, milestones, existing_requests, remaining_value, total_invoiced, current_fy` | 0.5d |
| 6 | Payment form | `finance/payment_form.html` | `invoice, payments, total_paid, remaining` | 0.5d |
| 7 | Finance officer dashboard | `finance/finance_officer_dashboard.html` | (view ported) | 0.5d |
| 8 | Client list | `clients/list.html` | `clients, filter_search, filter_type, filter_city, client_types` | 0.5d |
| 9 | Client form | `clients/form.html` | `client, client_types, is_edit` | 0.5d |
| 10 | Client view | `clients/view.html` | `client, assignments, stats` | 0.5d |
| 11 | Client MIS | `clients/mis.html` | (view ported) | 0.5d |
| 12 | Assignment-clients link | `clients/assignment_clients.html` | (view ported) | 0.25d |
| 13 | User management | `admin/users.html` | `officers, offices, roles, filter_*, search` | 0.5d |
| 14 | Roles management | `admin/roles.html` | `officers, officer_roles, hierarchy, groups, offices, today, show_history` | 0.75d |

**Tier 1 subtotal: ~7 working days.** Training (1–3) finishes the half-done Phase-2/3
slice and makes the 80-20 recognition panel reachable.

### Tier 2 — Core operations (not selected, recommended next)

| # | Page | Template | Effort |
|---|---|---|---|
| 15 | Assignments list | `assignments/assignments_list.html` | 0.5d |
| 16 | Expenditure form | `assignments/expenditure_form.html` | 0.5d |
| 17 | Expenditure entry form | `assignments/expenditure_entry_form.html` | 0.5d |
| 18 | Utilization list | `utilization/list.html` | 0.5d |
| 19 | Utilization form | `utilization/form.html` | 0.5d |
| 20 | Utilization pending | `utilization/pending.html` | 0.5d |
| 21 | Utilization rectification | `utilization/rectification.html` | 0.5d |
| 22 | Utilization summary | `utilization/summary.html` | 0.5d |
| 23 | Proposals list | `proposals/list.html` | 0.5d |
| 24 | Proposal upload | `proposals/upload.html` | 0.5d |
| 25 | Proposal link | `proposals/link.html` | 0.5d |
| 26 | Dashboard summary | `dashboard_summary.html` | 0.5d |

**Tier 2 subtotal: ~6 working days.**

### Tier 3 — Reports & legacy MIS (lower priority)

| # | Page | Template | Effort / Note |
|---|---|---|---|
| 27 | Delay report | `reports/delays.html` | 0.75d |
| 28 | Physical progress | `reports/physical_progress.html` | 0.75d |
| 29 | Financial progress | `reports/financial_progress.html` | 0.75d |
| 30 | Profile | `profile/profile.html` | 0.5d |
| 31 | Change password | `profile/change_password.html` | 0.25d |
| 32 | Data export | `data_management/export.html` | 0.5d |
| 33 | Data import | `data_management/import.html` | 0.5d |
| 34 | Data config | `data_management/config.html` | 0.5d |
| 35 | Legacy MIS dashboard | `mis/dashboard.html` | **Retire, don't port** (replaced by Phase-3 dashboards) |
| 36 | Legacy MIS office detail | `mis/office_detail.html` | **Retire, don't port** |

**Tier 3 subtotal: ~5 working days** (excludes the 2 to retire).

---

## 4. Totals

| Tier | Pages | Effort |
|---|---|---|
| 1 — Priority (selected) | 14 | ~7 days |
| 2 — Core operations | 12 | ~6 days |
| 3 — Reports/profile/data | 8 (+2 retire) | ~5 days |
| **Total to port everything** | **34 + 2 retire** | **~18 working days** |

---

## 5. Recommended build sequence

Per your one-module-at-a-time discipline (build → test → you redeploy → verify → next):

1. **Training (1–3)** — smallest, finishes my own half-done slice; unblocks 80-20 panel.
2. **Finance (4–7)** — highest business value; where assignment revenue is recognised.
3. **Clients (8–12)** — master data many screens reference.
4. **User/Roles (13–14)** — moves admin off the raw Django admin.
5. Then Tier 2, then Tier 3.

Each module: write templates → `pytest` the routes (extend existing route tests) →
you rebuild zip, upload, `collectstatic`, restart → smoke-test → next.
**No migrations** for any of this (templates only), so production DB is never touched.

---

## 6. Per-module Definition of Done

- Template renders the view's existing context (tables, forms, stats).
- Matches the working pages' visual style (page-container, cards, `btn`, `badge`, `data-table`).
- A route test asserts HTTP 200 + a key piece of content (not the "coming soon" string).
- Full `pytest` suite stays green.
- `run_collectstatic` clean (manifest regenerates).
