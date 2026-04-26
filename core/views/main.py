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
    """
    Health probe (M0-REL-09). Returns a JSON report with a checks array.

    Severity model — only DB/critical issues return HTTP 503; soft failures
    (disk, backup freshness) return 200 with status='degraded' so the site
    keeps responding to upstream health probes that only check HTTP code.

    Each check returns (severity, detail). Severities:
      ok        — fine
      warn      — soft fail (degraded but app works)
      critical  — hard fail (app should be marked down)
    """
    import os
    import shutil
    import time
    from datetime import datetime
    from pathlib import Path
    from django.conf import settings
    from django.db import connection

    checks = []

    # 1. DB connectivity — CRITICAL
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks.append({"name": "database", "severity": "ok", "detail": "connected"})
    except Exception as e:
        checks.append({
            "name": "database", "severity": "critical",
            "detail": f"disconnected: {type(e).__name__}",
        })

    # 2. Pending migrations — WARN (deploy in progress is expected; long-running pending is not)
    try:
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan[:3])
            checks.append({
                "name": "migrations", "severity": "warn",
                "detail": f"{len(plan)} pending: {names}",
            })
        else:
            checks.append({"name": "migrations", "severity": "ok", "detail": "up to date"})
    except Exception as e:
        checks.append({
            "name": "migrations", "severity": "warn",
            "detail": f"could not introspect: {type(e).__name__}",
        })

    # 3. Disk space at PERSIST_DIR — WARN if >85% full or <2GB free
    try:
        persist = Path(getattr(settings, "PERSIST_DIR", settings.BASE_DIR))
        usage = shutil.disk_usage(str(persist))
        free_gb = usage.free / (1024 ** 3)
        used_pct = 100 * usage.used / usage.total
        if used_pct > 95 or free_gb < 1:
            sev = "critical"
        elif used_pct > 85 or free_gb < 2:
            sev = "warn"
        else:
            sev = "ok"
        checks.append({
            "name": "disk", "severity": sev,
            "detail": f"{used_pct:.0f}% used, {free_gb:.1f} GB free at {persist}",
        })
    except Exception as e:
        checks.append({
            "name": "disk", "severity": "warn",
            "detail": f"could not stat: {type(e).__name__}",
        })

    # 4. Log file freshness — WARN if not written to in >24h (silent app)
    try:
        log_file = Path(getattr(settings, "LOG_FILE", "") or "")
        if log_file and log_file.exists():
            age_hours = (time.time() - log_file.stat().st_mtime) / 3600
            sev = "warn" if age_hours > 24 else "ok"
            checks.append({
                "name": "log_file", "severity": sev,
                "detail": f"last write {age_hours:.1f}h ago",
            })
        else:
            checks.append({
                "name": "log_file", "severity": "ok",
                "detail": "no LOG_FILE configured" if not log_file else "log file not yet created",
            })
    except Exception as e:
        checks.append({
            "name": "log_file", "severity": "warn",
            "detail": f"could not stat: {type(e).__name__}",
        })

    # 5. Backup freshness — WARN if no DB backup in last 36h (cron should run daily)
    try:
        backup_dir = Path(getattr(settings, "PERSIST_DIR", settings.BASE_DIR)) / "backups"
        if backup_dir.exists():
            db_backups = sorted(backup_dir.glob("db_*.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
            if db_backups:
                age_h = (time.time() - db_backups[0].stat().st_mtime) / 3600
                sev = "warn" if age_h > 36 else "ok"
                checks.append({
                    "name": "backup", "severity": sev,
                    "detail": f"latest {db_backups[0].name} {age_h:.1f}h old",
                })
            else:
                checks.append({
                    "name": "backup", "severity": "warn",
                    "detail": "backups dir exists but is empty",
                })
        else:
            checks.append({
                "name": "backup", "severity": "warn",
                "detail": "no backups dir — cron not configured?",
            })
    except Exception as e:
        checks.append({
            "name": "backup", "severity": "warn",
            "detail": f"could not check: {type(e).__name__}",
        })

    # Aggregate
    has_critical = any(c["severity"] == "critical" for c in checks)
    has_warn = any(c["severity"] == "warn" for c in checks)
    if has_critical:
        status = "down"
        http_status = 503
    elif has_warn:
        status = "degraded"
        http_status = 200
    else:
        status = "ok"
        http_status = 200

    return JsonResponse({
        "status": status,
        "framework": "Django 6.0.3",
        "checks": checks,
    }, status=http_status)
