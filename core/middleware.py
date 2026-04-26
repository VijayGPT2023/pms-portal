"""
Custom middleware for PMS Portal.

  MaintenanceModeMiddleware (M0-REL-10) — site-wide read-only/closed mode
  toggleable from the admin panel via SiteConfig.

When SiteConfig['maintenance_mode_enabled'] == 'true':
  - Anonymous users and non-staff officers see a 503 maintenance page.
  - Staff (Django is_staff=True) bypass — they can still log in and use
    the admin panel to flip the switch back off.
  - Whitelisted paths always pass through:
      /health/         (health probe)
      /admin/          (so admin can disable the toggle)
      /static/, /media/  (assets the maintenance page itself needs)
      /login/, /logout/  (so admin can log in to flip the switch)
"""
from django.shortcuts import render

from core.models import SiteConfig


KEY_MAINTENANCE_MODE = "maintenance_mode_enabled"

WHITELIST_PREFIXES = (
    "/health/",
    "/admin/",
    "/static/",
    "/media/",
    "/login/",
    "/logout/",
)


def _is_maintenance_on():
    raw = SiteConfig.get(KEY_MAINTENANCE_MODE, "false")
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_maintenance_on() and not self._bypass(request):
            return render(request, "maintenance.html", status=503)
        return self.get_response(request)

    @staticmethod
    def _bypass(request):
        path = request.path
        if any(path.startswith(p) for p in WHITELIST_PREFIXES):
            return True
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_staff:
            return True
        return False
