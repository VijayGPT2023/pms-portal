# PMS Portal — Scope V2 (Frozen)

**Status:** Locked. No code changes outside this scope without explicit re-negotiation.
**Lock date:** 2026-04-21
**Owner:** Vijay Kumar, NPC
**Supersedes:** Organic scope accumulated since FastAPI→Django migration (2026-03-31).

---

## 1. Purpose

Reset the portal scope around a minimum viable core. Ship the minimum, stabilize, then add one feature at a time. Avoid scope creep and "data-heavy" MIS that no one uses.

Approach: **Repair (targeted refactor)**, not rebuild. Preserve the Django foundation (Officer master, auth, RBAC, django-auditlog, django-fsm, 1,727 imported assignments, Head Hub, 96 tests). Add new modules on top. Retire the 6-tab MIS Command Center and replace with three simpler dashboards.

---

## 2. Three Independent Work Streams

The system tracks three parallel streams, each with its own MIS. They do not merge.

| Stream | Entry Point | Revenue? | Entity |
|---|---|---|---|
| **Pre-WO** | Enquiry / Prelim Visit / Proposal | No (tracking only) | Enquiry, PrelimVisit, Proposal |
| **Revenue** | Work Order OR Training | Yes (80-20 split) | Assignment, Training |
| **Non-Revenue** | Task ID | No (man-days only) | NonRevenueTask |

**Design principle:** Work Order is the anchor of the Revenue stream. Pre-WO stages are optional and can be skipped. Once WO is registered, the path is mandatory and sequential.

---

## 3. Module Specifications

### 3.1 Pre-WO Tracking (new)

- Three optional stages: Enquiry → Prelim Visit → Proposal.
- Each is an independent entity with its own ID. An officer can register any stage without preceding stages.
- When a WO is later registered, it can optionally reference one or more prior-stage IDs (Enquiry ID / Prelim Visit ID / Proposal ID). Linkage is done by the **TL during page-1 WO fill** (§3.2), not at WO shell creation.
- A Pre-WO record can be closed with outcome: Converted to WO / Dropped / On Hold.
- **Applies to new records only.** Not retroactively applied to the 1,727 existing assignments.
- **Ownership:** Any Officer can create a Pre-WO record. GH approves. TL is not involved at Pre-WO stage — TL's role starts only once a WO is created from (or independently of) the Pre-WO record.
- Encouraged practice: officers register at earliest stage and update through the funnel.
- Pre-WO MIS shows conversion funnel (Enquiry count → Prelim count → Proposal count → WO count) and drop-off reasons.

### 3.2 Work Order Lifecycle (refactor of existing Assignment)

Workflow stages (existing, renamed only):

| Stage | Renamed To | Owner | Notes |
|---|---|---|---|
| REGISTRATION | WO Registration | RD/GH | Creates WO shell (reference + client) |
| TL_ASSIGNMENT | TL Assignment | RD/GH | Assigns Team Leader |
| DETAIL_ENTRY | Progressive Fill | TL | 5 independent sections, each free-edit until submitted. Page-1 includes Pre-WO ID linkage. |
| ACTIVE | Execution | TL | Auto-activates when all 5 sections approved |
| COMPLETED | Closure | System | On final payment (write-off deferred to Phase 4+) |

**5-section progressive approval (preserved as intentional design):**

Each section has independent draft → submit → GH-approve flow. TL is not forced to fill all sections upfront.

1. **WO Basic (page-1)** — ToRs, scope, contract value, client, dates, **linked Pre-WO IDs (if any)**. Approval unblocks work start.
2. **Cost Estimation** — Cost heads + milestone breakup.
3. **Milestones** — Physical + financial milestone definitions.
4. **Team** — Team Officer list with roles on the assignment.
5. **Revenue Allocation** — % share per Team Officer, sums to 100%.

Before a section's first GH approval, TL edits the section freely (draft mode).
After first approval, all edits route through the **EditRequest ladder** (§3.5).

System auto-activates (existing `try_auto_activate()` method) when all 5 sections approved.

### 3.3 Training Lifecycle (refactor)

Training is post-event entry — participant count and delivery details are uncertain pre-event.

- Registered **after** the programme is conducted.
- **Two-step revenue recognition (80-20, same as assignments):**
  1. On completion: TL registers attendance, expenditure, faculty utilization, invoice details → triggers **80% revenue recognition**.
  2. On payment receipt: TL records payment → triggers **20% revenue recognition**.
- Revenue split among faculty via AssignmentTeam-equivalent for Training.
- EditRequest ladder (§3.5) applies to Training post-registration edits.

### 3.4 Non-Revenue Activity (new)

- Entity: **NonRevenueTask** with Task ID.
- Booking is in **man-days only**. No cost estimation, no revenue allocation.
- Minimum fields: Task ID, description, owner officer, start/end dates, man-days booked, outcome.
- **Ownership:** Created by any Officer. GH approves.
- Kept entirely separate from Revenue stream. No merging in MIS.
- Non-Revenue MIS shows: total man-days by officer, by group/RD, by task category.

### 3.5 EditRequest Ladder (new)

Applies to edits on Cost, Milestone, Team, Revenue after a section's first GH approval.

| Edit Number (per section, per assignment) | Approver |
|---|---|
| 1 | GH/RD |
| 2 | GH/RD |
| 3 | GH/RD |
| 4 and beyond | DDG |

Rules:
- TL **always** proposes — no self-edit after first approval.
- Each section (Cost, Milestone, Team, Revenue) has its **own independent edit counter**. TL can be on edit 2 for Cost and edit 4 for Team simultaneously.
- Every edit requires a **reason** (mandatory free text).
- Full audit trail: who proposed, who approved, when, reason, diff of changed fields.
- Replaces the existing `change_requests` module (retire after migration).

### 3.6 Bulk Onboarding of Existing Assignments (existing Head Hub, finalize)

- Two-phase:
  1. **RD validates list** — reviews their group's assignment list imported from old system; corrects wrong entries; assigns TL per assignment.
  2. **TL fills retrospective details** — Basic details, Cost, Milestones, Team, Revenue allocation, Physical % till date, Invoice No./Date, Payment Amount/Date.
- **Window:** Opens on Day-1 of hosting. Close date is **Admin-configurable** via settings — default 3 months from Day-1, but Admin can extend or shorten as needed. After window closes, no more retrospective bulk registration (new WOs follow normal lifecycle).
- **"As-of" date** is TL's choice per assignment.
- **Tally integration limited:** Tally provides financial data only. For old assignments, TL manually enters historic Invoice # + Date and Payment Amount + Date.
- **Physical progress:** TL judgment — no system enforcement.
- Does not enforce Pre-WO linkage (the 1,727 records have no Pre-WO history).

### 3.7 Flag Button on Revenue Allocation (new, lightweight)

Grievance channel — minimum viable version. Full grievance workflow deferred.

- Every row in the revenue allocation table shows a **Flag** button to the affected Officer.
- Clicking opens a form: **reason (mandatory)**, submit.
- Creates a logged flag visible to TL (action owner), GH (oversight), and flagger. DDG/DG can see flag counts in MIS.
- Status: Open / Addressed / Withdrawn.
- No SLA, no auto-escalation, no formal adjudication. Purely a logged concern with audit trail.
- Typical resolution: TL raises an EditRequest on revenue allocation to address the flag.
- **Upgrade criterion (Phase 4+):** If flag volume is high or resolution rates are poor, upgrade to full grievance workflow with SLAs and DDG adjudication.

### 3.8 DG / DDG MIS (rebuild, simplified)

Current 6-tab MIS Command Center retired. Replaced with **three separate simpler dashboards**:

1. **Pre-WO MIS** — Conversion funnel; enquiries by RD; drop-off reasons.
2. **Revenue MIS** — Assignments + Training combined. 80-20 recognized revenue; officer-wise and RD-wise rollups.
3. **Non-Revenue MIS** — Man-days by officer, RD, task category.

**DG/DDG top level:** 4-6 KPI tiles per dashboard. Each tile shows one number + trend.

**Drill-down hierarchy:** Organization → Group/RD → Officer → Assignment/Task.

Design rule: **not data-heavy.** Each screen answers a specific question. If a screen requires the user to scan more than ~10 data points to find the answer, it is wrong.

---

## 4. Role & Revenue Model (preserved, restated)

### Roles

| Role | Type | Purpose |
|---|---|---|
| **Officer** | Base (universal) | Every user is an Officer. This is the revenue-earning identity. |
| **TL** | Admin (stackable) | Accountability for an assignment. No implicit revenue. |
| **GH / RD** | Admin (stackable) | Group/Regional head. Approves sections and EditRequests 1-3. |
| **DDG** | Admin (stackable) | Approves EditRequests 4+. |
| **DG** | Admin (stackable) | Top-level MIS consumer. |

One person can hold Officer + TL + GH + DDG simultaneously.

### Revenue rule (hard)

Revenue flows **only** via Officer + AssignmentTeam membership. Admin roles earn zero from administrative authority alone.

- A TL who wants a revenue share on their assignment must be **separately added as a Team Officer** on that assignment.
- A GH/DDG contributing man-days must likewise be explicitly added to the team.
- GH/DDG adding themselves to a team they supervise is **normal and self-approvable** — not treated as a conflict of interest.

Revenue MIS always joins: Assignment → AssignmentTeam → Officer. Never by admin role.

---

## 5. Approval Matrix

| Action | Created By | Approver |
|---|---|---|
| Pre-WO record (Enquiry / Prelim Visit / Proposal) | Any Officer | GH/RD |
| WO Registration (shell creation) | RD/GH | — |
| TL Assignment | RD/GH | — |
| Section first-time approval (any of 5 sections) | TL | GH/RD |
| EditRequest on Cost / Milestone / Team / Revenue — edits 1-3 | TL (proposes) | GH/RD |
| EditRequest on Cost / Milestone / Team / Revenue — edits 4+ | TL (proposes) | DDG |
| Training registration (post-event) | TL | GH/RD |
| Non-Revenue Task | Any Officer | GH/RD |
| Closure on final payment | System | — (automatic) |
| Write-off closure | TL (proposes) | DDG (Phase 4+) |
| Flag on revenue allocation | Any affected Officer | — (logged, no approval) |

---

## 6. What is Kept / Added / Retired

### Kept (no changes)
- Officer model, OfficerRole, multi-role stacking
- Custom email-based auth backend
- RBAC infrastructure
- django-auditlog on 10 models
- django-fsm on Assignment (state machine preserved, only renamed)
- InvoiceRequest, PaymentReceipt, OfficerRevenueLedger (80-20 logic)
- 1,727 imported assignments
- Head Hub (to be completed as Module 3.6)
- 96 tests
- Admin panel
- Officer master (§ #7 of user scope)

### Added
- Pre-WO entities: Enquiry, PrelimVisit, Proposal
- EditRequest model with per-section edit counter
- NonRevenueTask with man-days booking
- Flag model on revenue allocation
- Three new MIS dashboards (Pre-WO, Revenue, Non-Revenue)

### Retired
- 6-tab MIS Command Center (code and templates)
- Existing `change_requests` module (replaced by EditRequest)

---

## 7. Deferred Features (out of scope for V2)

| Feature | Trigger to revisit |
|---|---|
| Write-off on closure with justification | After V2 stable; before first real year-end |
| Full grievance workflow (SLA, auto-escalation, DDG adjudication, anonymity) | If Flag volume or unresolved rate shows the lightweight version is insufficient |
| Pre-WO tracking for historic assignments | Not planned — explicitly new-only |
| Conversion MIS (enquiry-to-WO ratios by officer/RD over time) | Only if DG specifically asks |
| Automated Tally reconciliation for historic invoices | Not in V2 — TL manually enters historic invoice/payment |

---

## 8. Phased Build Sequence

Target: **6 weeks** for V2.

### Phase 1 — Foundation refactor (2 weeks)
- Rename workflow stages (REGISTRATION→WO Registration, etc.). Cosmetic only, preserve `try_auto_activate()`.
- Add EditRequest model + per-section edit counter + 1-3/4+ approval routing.
- Retire existing `change_requests` module (migrate any open items).
- Complete Head Hub bulk onboarding flow (Module 3.6) — RD list validation + TL fill.
- Open 3-month bulk onboarding window.

### Phase 2 — New modules (2 weeks)
- Pre-WO entities (Enquiry, PrelimVisit, Proposal) + WO linkage screen.
- Non-Revenue Task module.
- Training 80-20 two-step (confirm existing implementation or refactor).
- Flag button on revenue allocation + notification + audit log.

### Phase 3 — MIS rebuild (1 week)
- Retire 6-tab MIS Command Center.
- Build three new dashboards: Pre-WO, Revenue, Non-Revenue.
- DG/DDG top-level KPI tiles with drill-down: Org → Group/RD → Officer → Assignment.
- Design constraint: ≤10 data points per screen, one question per screen.

### Phase 4 — Stabilization and UAT (1 week)
- Run `run-uat.sh` against full scope.
- Manual UAT with RDs and DDGs.
- Deferred features evaluated for Phase 5+ based on usage data.

---

## 9. Decision Log

| # | Decision | Date | Rationale |
|---|---|---|---|
| D1 | Repair over rebuild | 2026-04-21 | 1,727 records already imported; Django migration only 3 weeks old; rework cost too high |
| D2 | Pre-WO applies to new only | 2026-04-21 | Historic data has no Pre-WO history; don't force fabrication |
| D3 | 5-section progressive approval preserved | 2026-04-21 | Intentional flexibility — TL can start work after page-1 approval without waiting on team/milestone clarity |
| D4 | Edit ladder: 3 to GH, 4+ to DDG | 2026-04-21 | User preference |
| D5 | Bulk onboarding window = 3 months | 2026-04-21 | User decision |
| D6 | Tally gives financials only; TL manually enters historic invoice/payment | 2026-04-21 | Tally integration scope boundary |
| D7 | Training = 80-20 two-step (same as assignments) | 2026-04-21 | Consistency with assignment revenue model |
| D8 | Closure = final payment; write-off deferred | 2026-04-21 | Write-off needs separate policy definition |
| D9 | Officer = universal base; admin roles carry zero revenue | 2026-04-21 | Pre-existing rule, restated explicitly |
| D10 | GH self-approving own team membership is normal, not a conflict | 2026-04-21 | User confirmed |
| D11 | Flag button now; full grievance workflow deferred | 2026-04-21 | Capture disputes with audit trail; upgrade only if data justifies |
| D12 | 6-tab MIS retired; replaced with three simpler dashboards | 2026-04-21 | Current MIS is "data-heavy"; not used effectively |
| D13 | Pre-WO records: any Officer creates, GH approves | 2026-04-21 | Broad participation encouraged; TL role deferred to WO stage |
| D14 | Pre-WO → WO linkage done by TL during page-1 WO fill | 2026-04-21 | RD/GH creates WO shell; TL owns detail fill including linkage |
| D15 | Non-Revenue Task: any Officer creates, GH approves | 2026-04-21 | Same ownership pattern as Pre-WO |
| D16 | Bulk onboarding window opens Day-1 of hosting; close date Admin-configurable (default 3 months) | 2026-04-21 | Flexibility to extend if RDs/TLs need more time |
| D17 | MIS access matrix confirmed: DG/DDG see all 3 MIS; GH/RD see own group only; Officer sees self only | 2026-04-21 | Standard hierarchical visibility |

---

## 10. MIS Access Matrix (confirmed)

| Role | Pre-WO MIS | Revenue MIS | Non-Revenue MIS | Scope |
|---|---|---|---|---|
| DG | ✓ | ✓ | ✓ | Organization-wide |
| DDG | ✓ | ✓ | ✓ | Organization-wide |
| GH / RD | ✓ | ✓ | ✓ | Own group/region only |
| TL | ✓ | ✓ | ✓ | Own assignments only |
| Officer | ✓ | ✓ | ✓ | Self only |

Every dashboard respects the scope column at query time. No role-bypass except DG and DDG.

---

**End of SCOPE_V2.md. Scope frozen. Phase 1 can begin.**
