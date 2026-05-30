# SCOPE_V2 — Build Status

**Updated:** 2026-05-30
**Branch:** directadmin-deploy
**Baseline at start of this round:** 219 tests passing

Tracks implementation of [SCOPE_V2.md](SCOPE_V2.md) against the codebase.

---

## Phase status

| Phase | SCOPE_V2 | Status |
|---|---|---|
| Phase 1 — Foundation refactor | §8 | ✅ Complete (stage renames, EditRequest, change_requests retired, Head Hub) |
| Phase 2 — New modules | §8 | ✅ Complete (this round) |
| Phase 3 — MIS rebuild | §3.8 | ✅ Complete (this round) |
| Phase 4 — Stabilization & UAT | §8 | 🟡 In progress (full suite green; manual UAT pending) |
| M0 Phase 1.5 hardening (F.1–F.12) | Gap Report | ✅ Complete (prior round) |

---

## This round — slices delivered

| Slice | Spec | Commit | New tests |
|---|---|---|---|
| **G.2 Pre-WO pipeline** | §3.1 | `11a2f61` | 11 |
| **G.3 Non-Revenue man-days** | §3.4 | `4be5753` | 6 |
| **Training 80-20 recognition** | §3.3 | `92cbab7` | 6 |
| **G.4 Revenue flag button** | §3.7 | `499f13a` | 8 |
| **Phase 3 MIS rebuild** | §3.8 | `499f13a` | 7 |

**38 new tests, all passing.**

### G.2 — Pre-WO pipeline (§3.1)
- `PreWORecord` model: single stage-tagged entity (Enquiry / Prelim Visit / Proposal).
- Any officer creates → GH/RD approves → close with outcome (Converted / Dropped / On Hold) + optional WO link.
- Conversion funnel on list page. Office-scoped. Nav + admin + tests.

### G.3 — Non-Revenue man-days (§3.4)
- Added `man_days` field to `NonRevenueSuggestion`; captured on create + progress update.
- Replaced stub templates with real list/form/view UI showing man-days.
- **Fixed a pre-existing bug:** views redirected to URL names `core:non_revenue_view`/`_list`
  that did not exist (patterns were named `view_suggestion`/`list_suggestions`) — every
  approve/reject/update/complete would have 500'd. Standardized to `core:non_revenue_*`
  (kept a `list_suggestions` alias for back-compat).

### Training 80-20 (§3.3)
- Two-step post-event recognition mirroring the assignment model:
  - **Register completion** (actuals + invoice) → 80% recognized.
  - **Record payment** → 20% recognized.
- New `TrainingRevenueLedger` splits each tranche to faculty by `revenue_share_percent`
  (even-split fallback). Kept separate from the audited assignment ledger so existing
  80-20 logic is untouched.
- Ordering + idempotency guards. Real training view template with recognition panels.

### G.4 — Revenue flag (§3.7)
- `RevenueAllocationFlag`: affected officer flags own share (reason mandatory); TL/Head
  address with note; flagger withdraws. Status Open/Addressed/Withdrawn, audit-logged.
- Per-row flag button on the rebuilt revenue allocation template; resolution path points
  to the EditRequest ladder. No SLA/escalation (per spec).

### Phase 3 — MIS rebuild (§3.8)
- Three simpler dashboards replace the 6-tab Command Center in the nav:
  1. **Pre-WO MIS** — conversion funnel + by-office.
  2. **Revenue MIS** — assignments + training 80-20 (union of both ledgers), officer rollup.
  3. **Non-Revenue MIS** — man-days by officer / category.
- Role scoping per access matrix §10 (org / office / self).
- Legacy 6-tab URLs retained but unlinked (no longer in nav).

---

## Migrations added this round
- `0007_preworecord`
- `0008_nonrevenuesuggestion_man_days`
- `0009_trainingprogramme_…` (recognition fields + `TrainingRevenueLedger`)
- `0010_revenueallocationflag`

---

## Not done / deferred (unchanged from SCOPE_V2 §7)
- Write-off on closure, full grievance workflow, Pre-WO for historic assignments,
  conversion-ratio MIS, automated Tally reconciliation.
- Legacy 6-tab MIS code/templates not yet deleted — only removed from nav. Safe to
  delete once the new dashboards are confirmed in UAT.

## Suggested next (Phase 4)
1. Manual UAT of each new module with a real RD/GH/TL login.
2. Delete the retired 6-tab MIS code + templates once dashboards are signed off.
3. `run-uat.sh` pass against the running server.
