"""
Authentication signal handlers (M0-AUD-02, SEC-13).

- user_logged_in     → write ActivityLog row (login)
- user_logged_out    → write ActivityLog row (logout)
- user_login_failed  → write ActivityLog row (failed attempt) for security review
- user_locked_out    → email admins (django-axes signal) — fires once per lockout, not per attempt
"""
import logging
from django.conf import settings
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.core.mail import mail_admins
from django.dispatch import receiver

from core.models import ActivityLog


logger = logging.getLogger(__name__)


def _client_ip(request):
    if request is None:
        return ""
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


@receiver(user_logged_in)
def _log_login(sender, request, user, **kwargs):
    try:
        ActivityLog.objects.create(
            actor=user,
            action="LOGIN",
            entity_type="auth",
            entity_id=user.pk,
            remarks=f"Login from {_client_ip(request)}",
        )
    except Exception:
        logger.exception("Failed to write login ActivityLog")


@receiver(user_logged_out)
def _log_logout(sender, request, user, **kwargs):
    if user is None:
        return
    try:
        ActivityLog.objects.create(
            actor=user,
            action="LOGOUT",
            entity_type="auth",
            entity_id=user.pk,
            remarks=f"Logout from {_client_ip(request)}",
        )
    except Exception:
        logger.exception("Failed to write logout ActivityLog")


@receiver(user_login_failed)
def _log_failed_login(sender, credentials, request, **kwargs):
    """
    Failed-login audit (M0-AUD-05).

    ActivityLog requires a non-null actor, so failed attempts (no authenticated
    user) are NOT written to ActivityLog — they are written to django-axes's
    AccessAttempt table by the AxesStandaloneBackend, which is the proper
    destination for anonymous failed-login forensics.

    Here we just emit a structured log line for the security log file.
    """
    attempted = (credentials or {}).get("email") or (credentials or {}).get("username") or "unknown"
    ip = _client_ip(request)
    logger.warning("auth.login_failed user=%s ip=%s", attempted, ip)


# django-axes lockout email (M0-SEC-13)
try:
    from axes.signals import user_locked_out

    @receiver(user_locked_out)
    def _email_on_lockout(sender, request, username, ip_address, **kwargs):
        """Email admins when an account or IP is locked out by django-axes."""
        try:
            subject = f"[PMS] Account lockout: {username or '(unknown)'} from {ip_address}"
            body = (
                f"django-axes locked out a login attempt.\n\n"
                f"Username/email attempted: {username or 'unknown'}\n"
                f"Client IP: {ip_address or 'unknown'}\n"
                f"Failure limit: {getattr(settings, 'AXES_FAILURE_LIMIT', 5)}\n"
                f"Cooloff: {getattr(settings, 'AXES_COOLOFF_TIME', 1)} hour(s)\n\n"
                f"Review at /admin/axes/accessattempt/ or unlock via management command:\n"
                f"  python manage.py axes_reset_username {username}\n"
                f"  python manage.py axes_reset_ip {ip_address}\n"
            )
            mail_admins(subject, body, fail_silently=True)
        except Exception:
            logger.exception("Failed to send lockout email")

except ImportError:
    # axes not installed (e.g. minimal test env)
    pass
