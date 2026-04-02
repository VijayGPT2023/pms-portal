"""
Core views — auth, dashboard, and health check.
Remaining views will be added as templates are ported.
"""
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render


def root_redirect(request):
    """Redirect root to dashboard if logged in, else login."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("core:login")


def login_view(request):
    """Login page and form handler."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    error = None
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next", "/dashboard/")
            return redirect(next_url)
        else:
            error = "Invalid email or password."

    return render(request, "login.html", {"error": error})


def logout_view(request):
    """Log out and redirect to login."""
    logout(request)
    return redirect("core:login")


# Dashboard views are now in core/views/dashboard.py


def health_check(request):
    """Health check endpoint for deployment monitoring."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    return JsonResponse({
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "framework": "Django 6.0.3",
    })
