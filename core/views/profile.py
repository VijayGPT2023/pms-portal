"""
User profile views: view profile, change password, switch role.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import redirect, render

from core.models import Officer, OfficerRole, RevenueShare


@login_required
def view_profile(request):
    """Display user's own profile."""
    officer = request.user
    office_name = officer.office.office_name if officer.office else ""

    roles = OfficerRole.objects.filter(
        officer=officer,
        effective_to__isnull=True,
    ).order_by("-is_primary", "-effective_from")

    stats = RevenueShare.objects.filter(officer=officer).aggregate(
        assignment_count=Count("assignment", distinct=True),
        total_revenue=Sum("share_amount"),
    )
    stats["total_revenue"] = stats["total_revenue"] or 0

    return render(request, "profile/profile.html", {
        "officer": officer,
        "office_name": office_name,
        "roles": roles,
        "stats": stats,
        "message": request.GET.get("message"),
        "error": request.GET.get("error"),
    })


@login_required
def change_password_form(request):
    """Display password change form."""
    return render(request, "profile/change_password.html", {
        "error": request.GET.get("error"),
    })


@login_required
def change_password_submit(request):
    """Process password change request."""
    if request.method != "POST":
        return redirect("core:change_password")

    current_password = request.POST.get("current_password", "")
    new_password = request.POST.get("new_password", "")
    confirm_password = request.POST.get("confirm_password", "")

    if len(new_password) < 8:
        return redirect("/profile/change-password/?error=Password must be at least 8 characters")

    if new_password != confirm_password:
        return redirect("/profile/change-password/?error=New passwords do not match")

    if not request.user.check_password(current_password):
        return redirect("/profile/change-password/?error=Current password is incorrect")

    request.user.set_password(new_password)
    request.user.save()

    # Re-authenticate so session stays valid
    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, request.user)

    return redirect("/profile/?message=Password changed successfully")
