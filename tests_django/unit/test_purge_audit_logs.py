"""
F.10 — purge_audit_logs tests (M0-AUD-08, COMP-02, OPS-07).
"""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import ActivityLog


pytestmark = pytest.mark.django_db


def _backdate_activity_log(row, days):
    """ActivityLog.created_at is auto_now_add, so we update via raw queryset."""
    ts = timezone.now() - timedelta(days=days)
    ActivityLog.objects.filter(pk=row.pk).update(created_at=ts)


class TestPurgeAuditLogs:
    def test_purge_deletes_old_activity_logs(self, admin_user):
        old = ActivityLog.objects.create(
            actor=admin_user, action="LOGIN", entity_type="auth",
            entity_id=1, remarks="old",
        )
        recent = ActivityLog.objects.create(
            actor=admin_user, action="LOGIN", entity_type="auth",
            entity_id=2, remarks="recent",
        )
        _backdate_activity_log(old, 200)         # older than 180-day cutoff
        _backdate_activity_log(recent, 30)       # within window

        out = StringIO()
        call_command("purge_audit_logs", stdout=out)

        assert not ActivityLog.objects.filter(pk=old.pk).exists()
        assert ActivityLog.objects.filter(pk=recent.pk).exists()
        assert "Deleted" in out.getvalue()

    def test_dry_run_does_not_delete(self, admin_user):
        old = ActivityLog.objects.create(
            actor=admin_user, action="LOGIN", entity_type="auth",
            entity_id=1, remarks="old",
        )
        _backdate_activity_log(old, 200)

        out = StringIO()
        call_command("purge_audit_logs", dry_run=True, stdout=out)

        assert ActivityLog.objects.filter(pk=old.pk).exists()
        assert "WOULD DELETE" in out.getvalue()
        assert "Would delete" in out.getvalue()

    def test_custom_days_override(self, admin_user):
        # 50-day-old row: kept at 180 (default), deleted at 30 (override)
        row = ActivityLog.objects.create(
            actor=admin_user, action="LOGOUT", entity_type="auth",
            entity_id=1, remarks="50-day",
        )
        _backdate_activity_log(row, 50)

        # Default 180: kept
        call_command("purge_audit_logs")
        assert ActivityLog.objects.filter(pk=row.pk).exists()

        # Override 30: deleted
        call_command("purge_audit_logs", days=30)
        assert not ActivityLog.objects.filter(pk=row.pk).exists()

    def test_purge_handles_empty_tables_cleanly(self, db):
        out = StringIO()
        call_command("purge_audit_logs", stdout=out)
        text = out.getvalue()
        assert "Done" in text
