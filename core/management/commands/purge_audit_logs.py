"""
purge_audit_logs — delete audit log rows older than retention window
(M0-AUD-08, M0-COMP-02, M0-OPS-07).

Targets two tables:
  * auditlog.LogEntry (django-auditlog) — model-change audit
  * core.ActivityLog                    — login/logout + custom actions

Default retention: 180 days (CERT-In Direction No. 20(3)/2022-CERT-In).
Override per-run with --days, or globally via settings.AUDIT_LOG_RETENTION_DAYS.

Usage:
    # Dry-run (count only, don't delete)
    python manage.py purge_audit_logs --dry-run

    # Actually purge
    python manage.py purge_audit_logs

    # Custom retention
    python manage.py purge_audit_logs --days 365
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete audit log entries older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=None,
            help="Override retention (default: settings.AUDIT_LOG_RETENTION_DAYS or 180)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Count only, don't delete",
        )

    def handle(self, *args, **opts):
        from core.cron import heartbeat
        with heartbeat("purge_audit_logs", expected_interval_seconds=86400):
            self._do(opts)

    def _do(self, opts):
        days = opts["days"] if opts["days"] is not None else getattr(
            settings, "AUDIT_LOG_RETENTION_DAYS", 180,
        )
        cutoff = timezone.now() - timedelta(days=days)
        self.stdout.write(f"Cutoff: {cutoff.isoformat()} ({days} days ago)")
        dry = opts["dry_run"]

        total = 0

        # auditlog.LogEntry
        try:
            from auditlog.models import LogEntry
            qs = LogEntry.objects.filter(timestamp__lt=cutoff)
            n = qs.count()
            if dry:
                self.stdout.write(f"  WOULD DELETE auditlog.LogEntry: {n}")
            else:
                deleted, _ = qs.delete()
                self.stdout.write(f"  Deleted auditlog.LogEntry: {deleted}")
                n = deleted
            total += n
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"  Skipped auditlog.LogEntry: {type(e).__name__}: {e}"
            ))

        # core.ActivityLog
        try:
            from core.models import ActivityLog
            qs = ActivityLog.objects.filter(created_at__lt=cutoff)
            n = qs.count()
            if dry:
                self.stdout.write(f"  WOULD DELETE core.ActivityLog: {n}")
            else:
                deleted, _ = qs.delete()
                self.stdout.write(f"  Deleted core.ActivityLog: {deleted}")
                n = deleted
            total += n
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"  Skipped core.ActivityLog: {type(e).__name__}: {e}"
            ))

        verb = "Would delete" if dry else "Deleted"
        self.stdout.write(self.style.SUCCESS(
            f"Done. {verb} {total} rows older than {days} days."
        ))
