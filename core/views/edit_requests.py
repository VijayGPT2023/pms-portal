"""
EditRequest workflow views (SCOPE_V2 §3.5).

Post-approval edit ladder for assignment sections:
- Cost, Team, Milestone, Revenue
- Edits 1-3 per (assignment, section) -> GH/RD approver
- Edits 4+ -> DDG approver
- TL always proposes; no self-edit after first approval
- One PENDING EditRequest per (assignment, section) — atomic, no race
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_fsm import TransitionNotAllowed

from core.models import (
    ActivityLog,
    Assignment,
    AssignmentTeam,
    EditRequest,
    ExpenditureHead,
    ExpenditureItem,
    Milestone,
    Officer,
    OfficerRole,
    RevenueShare,
)

__all__ = [
    "inbox",
    "detail",
    "propose_form",
    "approve",
    "reject",
    "withdraw",
]

# ------------------------------------------------------------------
# Role helpers (mirror approvals._is_head / _is_admin semantics)
# ------------------------------------------------------------------

GH_ROLES = {"RD_HEAD", "GROUP_HEAD", "DDG-I", "DDG-II", "DG", "ADMIN"}
DDG_ROLES = {"DDG-I", "DDG-II", "DG", "ADMIN"}


def _user_roles(user):
    primary = (user.admin_role_id or "").upper()
    extras = set(
        OfficerRole.objects.filter(officer=user.officer_id)
        .values_list("role_type", flat=True)
    )
    return {primary} | {r.upper() for r in extras if r}


def _can_approve(user, edit_request):
    roles = _user_roles(user)
    if edit_request.required_approver_role == "DDG":
        return bool(roles & DDG_ROLES)
    return bool(roles & GH_ROLES)


def _is_proposer(user, edit_request):
    return edit_request.proposed_by_id == user.officer_id


# ------------------------------------------------------------------
# Section snapshot / apply helpers
# ------------------------------------------------------------------

def _snapshot_cost(assignment):
    return [
        {
            "head_code": ei.head.head_code,
            "head_name": ei.head.head_name,
            "estimated_amount": float(ei.estimated_amount or 0),
            "remarks": ei.remarks or "",
        }
        for ei in ExpenditureItem.objects.filter(assignment=assignment)
        .select_related("head")
        .order_by("head__head_code")
    ]


def _apply_cost(assignment, new_snapshot):
    """Replace ExpenditureItem rows with new_snapshot (keyed by head_code)."""
    by_code = {row["head_code"]: row for row in new_snapshot}
    existing = {
        ei.head.head_code: ei
        for ei in ExpenditureItem.objects.filter(assignment=assignment)
        .select_related("head")
    }
    for code, row in by_code.items():
        if code in existing:
            ei = existing[code]
            ei.estimated_amount = float(row["estimated_amount"])
            ei.remarks = row.get("remarks", "")
            ei.save(update_fields=["estimated_amount", "remarks", "updated_at"])
        else:
            head = ExpenditureHead.objects.filter(head_code=code).first()
            if not head:
                continue
            ExpenditureItem.objects.create(
                assignment=assignment, head=head,
                estimated_amount=float(row["estimated_amount"]),
                remarks=row.get("remarks", ""),
            )
    for code, ei in existing.items():
        if code not in by_code:
            ei.delete()


def _snapshot_team(assignment):
    return [
        {
            "officer_id": tm.officer_id,
            "officer_name": str(tm.officer),
            "role": tm.role,
            "is_active": bool(tm.is_active),
        }
        for tm in AssignmentTeam.objects.filter(assignment=assignment)
        .select_related("officer")
        .order_by("officer_id")
    ]


def _apply_team(assignment, new_snapshot):
    by_id = {row["officer_id"]: row for row in new_snapshot}
    existing = {
        tm.officer_id: tm
        for tm in AssignmentTeam.objects.filter(assignment=assignment)
    }
    for oid, row in by_id.items():
        if oid in existing:
            tm = existing[oid]
            tm.role = row.get("role", tm.role)
            tm.is_active = bool(row.get("is_active", True))
            tm.save(update_fields=["role", "is_active"])
        else:
            officer = Officer.objects.filter(officer_id=oid).first()
            if not officer:
                continue
            AssignmentTeam.objects.create(
                assignment=assignment, officer=officer,
                role=row.get("role", AssignmentTeam.Role.MEMBER),
                is_active=bool(row.get("is_active", True)),
            )
    for oid, tm in existing.items():
        if oid not in by_id:
            tm.delete()


def _snapshot_milestone(assignment):
    return [
        {
            "milestone_no": ms.milestone_no,
            "title": ms.title,
            "target_date": ms.target_date.isoformat() if ms.target_date else None,
            "invoice_percent": float(ms.invoice_percent or 0),
            "invoice_amount": float(ms.invoice_amount or 0),
        }
        for ms in Milestone.objects.filter(assignment=assignment)
        .order_by("milestone_no")
    ]


def _apply_milestone(assignment, new_snapshot):
    from datetime import date
    by_no = {row["milestone_no"]: row for row in new_snapshot}
    existing = {
        ms.milestone_no: ms
        for ms in Milestone.objects.filter(assignment=assignment)
    }
    for no, row in by_no.items():
        td = row.get("target_date")
        td_val = date.fromisoformat(td) if td else None
        if no in existing:
            ms = existing[no]
            ms.title = row.get("title", ms.title)
            ms.target_date = td_val
            ms.invoice_percent = float(row.get("invoice_percent", 0))
            ms.invoice_amount = float(row.get("invoice_amount", 0))
            ms.save(update_fields=[
                "title", "target_date", "invoice_percent", "invoice_amount",
            ])
        else:
            Milestone.objects.create(
                assignment=assignment, milestone_no=no,
                title=row.get("title", ""),
                target_date=td_val,
                invoice_percent=float(row.get("invoice_percent", 0)),
                invoice_amount=float(row.get("invoice_amount", 0)),
            )
    for no, ms in existing.items():
        if no not in by_no:
            ms.delete()


def _snapshot_revenue(assignment):
    return [
        {
            "officer_id": rs.officer_id,
            "officer_name": str(rs.officer),
            "share_percent": float(rs.share_percent or 0),
        }
        for rs in RevenueShare.objects.filter(assignment=assignment)
        .select_related("officer")
        .order_by("officer_id")
    ]


def _apply_revenue(assignment, new_snapshot):
    total = sum(float(r.get("share_percent", 0)) for r in new_snapshot)
    if abs(total - 100.0) > 0.01:
        raise ValueError(f"Revenue shares must sum to 100% (got {total:.2f}%)")
    by_id = {row["officer_id"]: row for row in new_snapshot}
    existing = {
        rs.officer_id: rs
        for rs in RevenueShare.objects.filter(assignment=assignment)
    }
    for oid, row in by_id.items():
        if oid in existing:
            rs = existing[oid]
            rs.share_percent = float(row["share_percent"])
            rs.save(update_fields=["share_percent", "updated_at"])
        else:
            officer = Officer.objects.filter(officer_id=oid).first()
            if not officer:
                continue
            RevenueShare.objects.create(
                assignment=assignment, officer=officer,
                share_percent=float(row["share_percent"]),
            )
    for oid, rs in existing.items():
        if oid not in by_id:
            rs.delete()


SECTION_HANDLERS = {
    "COST": (_snapshot_cost, _apply_cost),
    "TEAM": (_snapshot_team, _apply_team),
    "MILESTONE": (_snapshot_milestone, _apply_milestone),
    "REVENUE": (_snapshot_revenue, _apply_revenue),
}


def _section_status_field(section):
    return {
        "COST": "cost_approval_status",
        "TEAM": "team_approval_status",
        "MILESTONE": "milestone_approval_status",
        "REVENUE": "revenue_approval_status",
    }[section]


def _section_is_approved(assignment, section):
    return getattr(assignment, _section_status_field(section)) == "APPROVED"


# ------------------------------------------------------------------
# Snapshot parsing from POST data
# ------------------------------------------------------------------

def _parse_snapshot_from_post(section, post):
    """Build a new_snapshot list from POST form data. Form sends parallel arrays."""
    if section == "COST":
        codes = post.getlist("head_code")
        amounts = post.getlist("estimated_amount")
        remarks = post.getlist("remarks")
        rows = []
        for i, code in enumerate(codes):
            code = (code or "").strip()
            if not code:
                continue
            try:
                amt = float(amounts[i] or 0)
            except (ValueError, IndexError):
                amt = 0.0
            rows.append({
                "head_code": code,
                "estimated_amount": amt,
                "remarks": (remarks[i] if i < len(remarks) else "") or "",
            })
        return rows

    if section == "TEAM":
        ids = post.getlist("officer_id")
        roles = post.getlist("role")
        active_set = set(post.getlist("is_active"))
        rows = []
        for i, oid in enumerate(ids):
            oid = (oid or "").strip()
            if not oid:
                continue
            rows.append({
                "officer_id": oid,
                "role": (roles[i] if i < len(roles) else "MEMBER") or "MEMBER",
                "is_active": str(i) in active_set or oid in active_set,
            })
        return rows

    if section == "MILESTONE":
        nos = post.getlist("milestone_no")
        titles = post.getlist("title")
        targets = post.getlist("target_date")
        ipcts = post.getlist("invoice_percent")
        iamts = post.getlist("invoice_amount")
        rows = []
        for i, no in enumerate(nos):
            try:
                no_int = int(no)
            except (TypeError, ValueError):
                continue
            rows.append({
                "milestone_no": no_int,
                "title": (titles[i] if i < len(titles) else "") or "",
                "target_date": (targets[i] if i < len(targets) else "") or None,
                "invoice_percent": float(ipcts[i] or 0) if i < len(ipcts) else 0.0,
                "invoice_amount": float(iamts[i] or 0) if i < len(iamts) else 0.0,
            })
        return rows

    if section == "REVENUE":
        ids = post.getlist("officer_id")
        pcts = post.getlist("share_percent")
        rows = []
        for i, oid in enumerate(ids):
            oid = (oid or "").strip()
            if not oid:
                continue
            try:
                pct = float(pcts[i] or 0)
            except (ValueError, IndexError):
                pct = 0.0
            rows.append({"officer_id": oid, "share_percent": pct})
        return rows

    raise ValueError(f"Unknown section: {section}")


# ------------------------------------------------------------------
# Views
# ------------------------------------------------------------------

@login_required
def inbox(request):
    """List EditRequests visible to the current user.

    - Approver sees PENDING requests they're allowed to act on.
    - Proposer sees their own requests (any status).
    """
    user = request.user
    roles = _user_roles(user)

    pending = EditRequest.objects.filter(status="PENDING").select_related(
        "assignment", "proposed_by",
    )
    actionable = []
    for er in pending:
        if er.required_approver_role == "DDG" and (roles & DDG_ROLES):
            actionable.append(er)
        elif er.required_approver_role == "GH" and (roles & GH_ROLES):
            actionable.append(er)

    mine = EditRequest.objects.filter(
        proposed_by_id=user.officer_id,
    ).select_related("assignment").order_by("-proposed_at")[:50]

    return render(request, "edit_requests/inbox.html", {
        "actionable": actionable,
        "mine": mine,
    })


@login_required
def detail(request, request_id):
    er = get_object_or_404(
        EditRequest.objects.select_related("assignment", "proposed_by", "reviewed_by"),
        pk=request_id,
    )
    try:
        change = json.loads(er.change_data) if er.change_data else {}
    except json.JSONDecodeError:
        change = {}

    can_approve = er.status == "PENDING" and _can_approve(request.user, er)
    can_withdraw = er.status == "PENDING" and _is_proposer(request.user, er)

    return render(request, "edit_requests/detail.html", {
        "er": er,
        "old_snapshot": change.get("old", []),
        "new_snapshot": change.get("new", []),
        "can_approve": can_approve,
        "can_withdraw": can_withdraw,
    })


@login_required
def propose_form(request, assignment_id, section):
    """GET: render the propose form pre-filled with current section data.
    POST: create the EditRequest with snapshot.
    """
    section = section.upper()
    if section not in SECTION_HANDLERS:
        messages.error(request, f"Unknown section: {section}")
        return redirect("core:dashboard")

    assignment = get_object_or_404(Assignment, pk=assignment_id)

    # Only TL (or admin) can propose
    is_tl = (
        assignment.team_leader_id
        and assignment.team_leader_id == request.user.officer_id
    )
    is_admin_user = (request.user.admin_role_id or "").upper() in {"ADMIN", "DG"}
    if not (is_tl or is_admin_user):
        messages.error(request, "Only the team leader can propose edits.")
        return redirect("core:assignment_view", assignment_id=assignment_id)

    if not _section_is_approved(assignment, section):
        messages.error(
            request,
            f"{section.title()} section is not yet approved. Edit it directly.",
        )
        return redirect("core:assignment_view", assignment_id=assignment_id)

    # Block if a PENDING request already exists for this section
    pending = EditRequest.objects.filter(
        assignment=assignment, section=section, status="PENDING",
    ).first()
    if pending and request.method == "GET":
        messages.warning(
            request,
            f"A pending EditRequest (#{pending.edit_number}) already exists for this section.",
        )
        return redirect("core:edit_request_detail", request_id=pending.pk)
    if pending and request.method == "POST":
        messages.error(request, "Cannot propose — a pending request already exists.")
        return redirect("core:edit_request_detail", request_id=pending.pk)

    snapshot_fn, _ = SECTION_HANDLERS[section]
    old_snapshot = snapshot_fn(assignment)

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()
        if not reason:
            messages.error(request, "Reason is required.")
            return render(request, f"edit_requests/propose_{section.lower()}.html", {
                "assignment": assignment, "section": section,
                "old_snapshot": old_snapshot,
            })

        try:
            new_snapshot = _parse_snapshot_from_post(section, request.POST)
        except (ValueError, TypeError) as e:
            messages.error(request, f"Invalid form data: {e}")
            return render(request, f"edit_requests/propose_{section.lower()}.html", {
                "assignment": assignment, "section": section,
                "old_snapshot": old_snapshot,
            })

        change_data = json.dumps({
            "section": section,
            "old": old_snapshot,
            "new": new_snapshot,
        })

        with transaction.atomic():
            er = EditRequest.objects.create(
                assignment=assignment,
                section=section,
                proposed_by=request.user,
                reason=reason,
                change_data=change_data,
            )
            ActivityLog.objects.create(
                actor_id=request.user.officer_id,
                action="CREATE",
                entity_type="edit_request",
                entity_id=er.pk,
                remarks=f"Proposed edit #{er.edit_number} on {section} of {assignment.assignment_no}",
            )

        messages.success(
            request,
            f"EditRequest #{er.edit_number} submitted to {er.required_approver_role}.",
        )
        return redirect("core:edit_request_detail", request_id=er.pk)

    # GET: render section-specific form
    extra = {}
    if section == "COST":
        extra["heads"] = list(ExpenditureHead.objects.filter(is_active=True).order_by("head_code"))
    elif section in {"TEAM", "REVENUE"}:
        extra["officers"] = list(
            Officer.objects.filter(is_active=True).order_by("name")[:500]
        )

    return render(request, f"edit_requests/propose_{section.lower()}.html", {
        "assignment": assignment,
        "section": section,
        "old_snapshot": old_snapshot,
        **extra,
    })


@login_required
@require_POST
def approve(request, request_id):
    er = get_object_or_404(
        EditRequest.objects.select_related("assignment"), pk=request_id,
    )
    if er.status != "PENDING":
        messages.error(request, f"Request is already {er.status}.")
        return redirect("core:edit_request_detail", request_id=er.pk)
    if not _can_approve(request.user, er):
        messages.error(
            request,
            f"You are not authorized to approve this request (needs {er.required_approver_role}).",
        )
        return redirect("core:edit_request_detail", request_id=er.pk)

    notes = (request.POST.get("review_notes") or "").strip()

    try:
        change = json.loads(er.change_data or "{}")
    except json.JSONDecodeError:
        messages.error(request, "Cannot apply: change_data is corrupt.")
        return redirect("core:edit_request_detail", request_id=er.pk)

    _, apply_fn = SECTION_HANDLERS[er.section]
    try:
        with transaction.atomic():
            apply_fn(er.assignment, change.get("new", []))
            er.approve(reviewer=request.user, notes=notes)
            er.save()
            ActivityLog.objects.create(
                actor_id=request.user.officer_id,
                action="APPROVE",
                entity_type="edit_request",
                entity_id=er.pk,
                remarks=f"Approved edit #{er.edit_number} on {er.section} of {er.assignment.assignment_no}",
            )
    except (TransitionNotAllowed, ValueError) as e:
        messages.error(request, f"Could not approve: {e}")
        return redirect("core:edit_request_detail", request_id=er.pk)

    messages.success(request, f"EditRequest #{er.edit_number} approved and applied.")
    return redirect("core:edit_request_detail", request_id=er.pk)


@login_required
@require_POST
def reject(request, request_id):
    er = get_object_or_404(EditRequest, pk=request_id)
    if er.status != "PENDING":
        messages.error(request, f"Request is already {er.status}.")
        return redirect("core:edit_request_detail", request_id=er.pk)
    if not _can_approve(request.user, er):
        messages.error(request, "You are not authorized to reject this request.")
        return redirect("core:edit_request_detail", request_id=er.pk)

    notes = (request.POST.get("review_notes") or "").strip()
    if not notes:
        messages.error(request, "Rejection requires review notes.")
        return redirect("core:edit_request_detail", request_id=er.pk)

    try:
        with transaction.atomic():
            er.reject(reviewer=request.user, notes=notes)
            er.save()
            ActivityLog.objects.create(
                actor_id=request.user.officer_id,
                action="REJECT",
                entity_type="edit_request",
                entity_id=er.pk,
                remarks=notes,
            )
    except (TransitionNotAllowed, ValueError) as e:
        messages.error(request, f"Could not reject: {e}")
        return redirect("core:edit_request_detail", request_id=er.pk)

    messages.success(request, f"EditRequest #{er.edit_number} rejected.")
    return redirect("core:edit_request_detail", request_id=er.pk)


@login_required
@require_POST
def withdraw(request, request_id):
    er = get_object_or_404(EditRequest, pk=request_id)
    if er.status != "PENDING":
        messages.error(request, f"Request is already {er.status}.")
        return redirect("core:edit_request_detail", request_id=er.pk)
    if not _is_proposer(request.user, er):
        messages.error(request, "Only the proposer can withdraw a request.")
        return redirect("core:edit_request_detail", request_id=er.pk)

    try:
        with transaction.atomic():
            er.withdraw()
            er.save()
            ActivityLog.objects.create(
                actor_id=request.user.officer_id,
                action="UPDATE",
                entity_type="edit_request",
                entity_id=er.pk,
                remarks="Withdrawn by proposer",
            )
    except TransitionNotAllowed as e:
        messages.error(request, f"Could not withdraw: {e}")
        return redirect("core:edit_request_detail", request_id=er.pk)

    messages.success(request, f"EditRequest #{er.edit_number} withdrawn.")
    return redirect("core:edit_request_detail", request_id=er.pk)
