"""
Custom middleware for PMS Portal.

  MaintenanceModeMiddleware (M0-REL-10) — site-wide read-only/closed mode
  toggleable from the admin panel via SiteConfig.

  SecurityHeadersMiddleware (M0-SEC-03) — sets CSP, Permissions-Policy,
  and Referrer-Policy headers on every response.

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


# ---------------------------------------------------------------------------
# Security headers (M0-SEC-03, M0-SEC-04)
# ---------------------------------------------------------------------------

# Content Security Policy. Phased rollout (SCOPE_V2 / M0 §SEC-04):
#   1. Ship in Report-Only mode (browser sends violation reports, doesn't block)
#   2. Audit reports for 2-4 weeks; tighten policy as needed
#   3. Flip to enforce mode by setting CSP_ENFORCE = True in local_settings.py
#
# Inline 'unsafe-inline' is currently REQUIRED because base.html uses inline
# <script> blocks (sidebar toggle, cookie notice, axes lockout countdown).
# Migration path: extract to /static/js/ and drop 'unsafe-inline' before enforce.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

# Permissions-Policy: deny everything the portal doesn't legitimately use.
# Internal officer portal — no camera, mic, geolocation, payment, USB, etc.
DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), ambient-light-sensor=(), autoplay=(), battery=(), "
    "camera=(), display-capture=(), document-domain=(), encrypted-media=(), "
    "fullscreen=(self), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), midi=(), payment=(), picture-in-picture=(), "
    "publickey-credentials-get=(), screen-wake-lock=(), sync-xhr=(), "
    "usb=(), web-share=(), xr-spatial-tracking=()"
)


class SecurityHeadersMiddleware:
    """Inject CSP, Permissions-Policy, Referrer-Policy on every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        from django.conf import settings as _s

        # CSP — Report-Only by default, enforce when CSP_ENFORCE = True
        csp = getattr(_s, "CONTENT_SECURITY_POLICY", DEFAULT_CSP)
        if getattr(_s, "CSP_ENFORCE", False):
            response.setdefault("Content-Security-Policy", csp)
        else:
            response.setdefault("Content-Security-Policy-Report-Only", csp)

        # Permissions-Policy
        pp = getattr(_s, "PERMISSIONS_POLICY", DEFAULT_PERMISSIONS_POLICY)
        response.setdefault("Permissions-Policy", pp)

        # Referrer-Policy: no-referrer-when-downgrade is Django's default via
        # SECURE_REFERRER_POLICY but we set explicitly here for completeness
        # in case SecurityMiddleware ordering changes.
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        return response
