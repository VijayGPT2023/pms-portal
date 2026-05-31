"""
Admin views for user management, role management, and officer transfers.
"""
import secrets
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render

from core.models import (
    ActivityLog, DesignationHistory, Group, Office, Officer,
    OfficerHistory, OfficerRole, OfficeTransferHistory, ReportingHierarchy,
)

ROLE_NAMES = {
    "ADMIN": "System Administrator",
    "DG": "Director General",
    "DDG-I": "Deputy Director General - I",
    "DDG-II": "Deputy Director General - II",
    "RD_HEAD": "Regional Director / Head",
    "GROUP_HEAD": "Group Head",
    "TEAM_LEADER": "Team Leader",
    "FINANCE": "Finance Officer",
    "OFFICER": "Officer",
}
ALL_ROLES = list(ROLE_NAMES.keys())


def _require_admin(user):
    """Check if user is admin."""
    return user.is_staff or user.admin_role_id == "ADMIN"


@login_required
def user_management_page(request):
    """Display user management page."""
    if not _require_admin(request.user):
        return redirect("core:dashboard")

    filter_office = request.GET.get("filter_office")
    filter_role = request.GET.get("filter_role")
    search = request.GET.get("search")

    qs = Officer.objects.all()
    if filter_office:
        qs = qs.filter(office__office_id=filter_office)
    if filter_role:
        if filter_role == "OFFICER":
            qs = qs.filter(Q(admin_role_id="") | Q(admin_role_id__isnull=True))
        else:
            qs = qs.filter(admin_role_id=filter_role)
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(email__icontains=search))

    qs = qs.order_by("office__office_id", "name")
    offices = Office.objects.order_by("office_id")

    return render(request, "admin/users.html", {
        "officers": qs,
        "offices": offices,
        "roles": ROLE_NAMES,
        "filter_office": filter_office,
        "filter_role": filter_role,
        "search": search,
    })


@login_required
def update_user_role(request):
    """Update a user's role."""
    if request.method != "POST" or not _require_admin(request.user):
        return redirect("core:user_management")

    officer_id = request.POST.get("officer_id")
    role = request.POST.get("role") or ""
    if role and role not in ALL_ROLES:
        role = ""

    try:
        officer = Officer.objects.get(officer_id=officer_id)
        officer.admin_role_id = role
        officer.save(update_fields=["admin_role_id"])

        ActivityLog.objects.create(
            actor=request.user,
            action="UPDATE",
            entity_type="officer",
            remarks=f"Role changed for {officer_id} to {role}",
        )
    except Officer.DoesNotExist:
        pass

    return redirect("core:user_management")


@login_required
def reset_user_password(request):
    """Reset a user's password."""
    if request.method != "POST" or not _require_admin(request.user):
        return redirect("core:user_management")

    officer_id = request.POST.get("officer_id")
    try:
        officer = Officer.objects.get(officer_id=officer_id)
    except Officer.DoesNotExist:
        return redirect("core:user_management")

    new_password = secrets.token_urlsafe(8)
    officer.set_password(new_password)
    officer.save()

    ActivityLog.objects.create(
        actor=request.user,
        action="UPDATE",
        entity_type="officer",
        remarks=f"Password reset for {officer_id}",
    )

    # Return to page with the reset result
    officers = Officer.objects.order_by("office__office_id", "name")
    offices = Office.objects.order_by("office_id")

    return render(request, "admin/users.html", {
        "officers": officers,
        "offices": offices,
        "roles": ROLE_NAMES,
        "reset_result": {
            "name": officer.name,
            "password": new_password,
        },
    })


@login_required
def roles_management_page(request):
    """Display role and hierarchy management page."""
    if not _require_admin(request.user):
        return redirect("core:dashboard")

    show_history = request.GET.get("show_history") == "true"
    today = date.today()

    officers = Officer.objects.filter(is_active=True).order_by("name")

    role_qs = OfficerRole.objects.select_related("officer")
    if not show_history:
        role_qs = role_qs.filter(effective_to__isnull=True)
    role_qs = role_qs.order_by("officer__name", "role_type")

    hierarchy = ReportingHierarchy.objects.filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    ).order_by("entity_type", "entity_value")

    groups = Group.objects.order_by("group_code")
    offices = Office.objects.order_by("office_id")

    return render(request, "admin/roles.html", {
        "officers": officers,
        "officer_roles": role_qs,
        "hierarchy": hierarchy,
        "groups": groups,
        "offices": offices,
        "today": today.isoformat(),
        "show_history": show_history,
    })


@login_required
def assign_role(request):
    """Assign a role to an officer."""
    if request.method != "POST" or not _require_admin(request.user):
        return redirect("core:roles_management")

    officer_id = request.POST.get("officer_id")
    role_type = request.POST.get("role_type")
    scope_type = request.POST.get("scope_type") or "GLOBAL"
    scope_value = request.POST.get("scope_value") or ""
    is_primary = bool(int(request.POST.get("is_primary", 0)))
    effective_from = request.POST.get("effective_from") or date.today().isoformat()
    order_reference = request.POST.get("order_reference") or ""

    officer = Officer.objects.get(officer_id=officer_id)

    # End existing active role of same type for this scope
    if scope_value:
        OfficerRole.objects.filter(
            role_type=role_type, scope_value=scope_value,
            effective_to__isnull=True,
        ).exclude(officer=officer).update(effective_to=effective_from)

    # Check if officer already has this exact role active
    existing = OfficerRole.objects.filter(
        officer=officer, role_type=role_type,
        scope_value=scope_value, effective_to__isnull=True,
    ).exists()

    if not existing:
        OfficerRole.objects.create(
            officer=officer,
            role_type=role_type,
            scope_type=scope_type,
            scope_value=scope_value,
            is_primary=is_primary,
            effective_from=effective_from,
            order_reference=order_reference,
            assigned_by=request.user.officer_id,
        )

    # Update legacy admin_role_id if primary
    if is_primary:
        officer.admin_role_id = role_type
        officer.save(update_fields=["admin_role_id"])

    # Record in officer_history
    OfficerHistory.objects.create(
        officer=officer,
        change_type="ROLE_ASSIGN",
        field_name="role",
        new_value=f"{role_type}:{scope_value or 'GLOBAL'}",
        effective_from=effective_from,
        order_reference=order_reference,
        remarks=f"Role {role_type} assigned",
        changed_by=request.user.officer_id,
    )

    ActivityLog.objects.create(
        actor=request.user,
        action="CREATE",
        entity_type="role",
        new_data=f"role={role_type},scope={scope_value},from={effective_from}",
        remarks=f"Role assigned to {officer_id}",
    )
    return redirect("core:roles_management")


@login_required
def remove_role(request):
    """End a role assignment."""
    if request.method != "POST" or not _require_admin(request.user):
        return redirect("core:roles_management")

    role_id = int(request.POST.get("role_id", 0))
    effective_to = request.POST.get("effective_to") or date.today().isoformat()
    order_reference = request.POST.get("order_reference", "")
    remarks = request.POST.get("remarks", "")

    try:
        role = OfficerRole.objects.get(pk=role_id)
        role.effective_to = effective_to
        role.save(update_fields=["effective_to"])

        OfficerHistory.objects.create(
            officer=role.officer,
            change_type="ROLE_REMOVE",
            field_name="role",
            old_value=f"{role.role_type}:{role.scope_value or 'GLOBAL'}",
            effective_from=str(role.effective_from),
            effective_to=effective_to,
            order_reference=order_reference,
            remarks=remarks or f"Role {role.role_type} ended",
            changed_by=request.user.officer_id,
        )

        ActivityLog.objects.create(
            actor=request.user,
            action="UPDATE",
            entity_type="role",
            entity_id=role_id,
            old_data=f"role={role.role_type}",
            remarks=f"Role ended for {role.officer.officer_id} on {effective_to}",
        )
    except OfficerRole.DoesNotExist:
        pass

    return redirect("core:roles_management")


@login_required
def transfer_officer(request):
    """Transfer an officer to a new office."""
    if request.method != "POST" or not _require_admin(request.user):
        return redirect("core:user_management")

    officer_id = request.POST.get("officer_id")
    to_office_id = request.POST.get("to_office_id")
    effective_from = request.POST.get("effective_from") or date.today().isoformat()
    transfer_order_no = request.POST.get("transfer_order_no", "")
    transfer_order_date = request.POST.get("transfer_order_date") or None
    remarks = request.POST.get("remarks", "")

    try:
        officer = Officer.objects.get(officer_id=officer_id)
    except Officer.DoesNotExist:
        return redirect("core:user_management")

    from_office = officer.office
    to_office = Office.objects.get(office_id=to_office_id)

    # End previous transfer record
    OfficeTransferHistory.objects.filter(
        officer=officer, effective_to__isnull=True,
    ).update(effective_to=effective_from)

    # Insert new transfer record
    OfficeTransferHistory.objects.create(
        officer=officer,
        from_office=from_office,
        to_office=to_office,
        effective_from=effective_from,
        transfer_order_no=transfer_order_no,
        transfer_order_date=transfer_order_date,
        remarks=remarks,
        updated_by=request.user.officer_id,
    )

    # Update officer's office
    officer.office = to_office
    officer.save(update_fields=["office"])

    # Record in officer_history
    OfficerHistory.objects.create(
        officer=officer,
        change_type="OFFICE_TRANSFER",
        field_name="office_id",
        old_value=from_office.office_id,
        new_value=to_office_id,
        effective_from=effective_from,
        order_reference=transfer_order_no,
        remarks=remarks,
        changed_by=request.user.officer_id,
    )

    ActivityLog.objects.create(
        actor=request.user,
        action="UPDATE",
        entity_type="officer",
        remarks=f"Transferred {officer_id} from {from_office.office_id} to {to_office_id}",
    )
    return redirect("core:user_management")
