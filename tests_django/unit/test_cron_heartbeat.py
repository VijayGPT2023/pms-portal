"""
F.11 — cron heartbeat tests (M0-OPS-08, M0-REL-13).
"""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.cron import heartbeat
from core.models import CronHeartbeat


pytestmark = pytest.mark.django_db


class TestHeartbeatContextManager:
    def test_success_records_status_and_duration(self, db):
        with heartbeat("test_job", expected_interval_seconds=3600):
            pass
        h = CronHeartbeat.objects.get(job_name="test_job")
        assert h.last_status == "success"
        assert h.last_run_at is not None
        assert h.last_duration_ms >= 0
        assert h.expected_interval_seconds == 3600
        assert h.last_error == ""

    def test_failure_records_status_and_reraises(self, db):
        with pytest.raises(ValueError):
            with heartbeat("test_fail", expected_interval_seconds=3600):
                raise ValueError("simulated")
        h = CronHeartbeat.objects.get(job_name="test_fail")
        assert h.last_status == "failure"
        assert "simulated" in h.last_error

    def test_overdue_when_never_run(self, db):
        h = CronHeartbeat.objects.create(
            job_name="never_run", expected_interval_seconds=86400,
        )
        assert h.is_overdue()

    def test_overdue_when_last_run_too_old(self, db):
        h = CronHeartbeat.objects.create(
            job_name="stale", expected_interval_seconds=3600,
            last_run_at=timezone.now() - timedelta(hours=5),
        )
        assert h.is_overdue()

    def test_not_overdue_when_recent(self, db):
        h = CronHeartbeat.objects.create(
            job_name="fresh", expected_interval_seconds=3600,
            last_run_at=timezone.now() - timedelta(minutes=30),
        )
        assert not h.is_overdue()


class TestCheckHeartbeatsCommand:
    def test_reports_overdue_jobs(self, db):
        CronHeartbeat.objects.create(
            job_name="late", expected_interval_seconds=3600,
            last_run_at=timezone.now() - timedelta(hours=10),
        )
        out = StringIO()
        call_command("check_heartbeats", stdout=out)
        text = out.getvalue()
        assert "OVERDUE" in text
        assert "1 overdue" in text

    def test_reports_failed_jobs(self, db):
        CronHeartbeat.objects.create(
            job_name="broken", expected_interval_seconds=3600,
            last_run_at=timezone.now() - timedelta(minutes=10),
            last_status="failure",
            last_error="boom",
        )
        out = StringIO()
        call_command("check_heartbeats", stdout=out)
        assert "FAILED" in out.getvalue()
        assert "1 failed" in out.getvalue()

    def test_all_ok_reports_zero(self, db):
        CronHeartbeat.objects.create(
            job_name="happy", expected_interval_seconds=3600,
            last_run_at=timezone.now() - timedelta(minutes=10),
            last_status="success",
        )
        out = StringIO()
        call_command("check_heartbeats", stdout=out)
        assert "0 overdue" in out.getvalue()
        assert "0 failed" in out.getvalue()


class TestHeartbeatIntegrationWithBackupCommand:
    def test_backup_files_writes_heartbeat(self, tmp_path):
        src = tmp_path / "uploads"
        src.mkdir()
        (src / "f.txt").write_text("x")
        out_dir = tmp_path / "out"
        call_command("backup_files", out_dir=str(out_dir), source=str(src))
        h = CronHeartbeat.objects.get(job_name="backup_files")
        assert h.last_status == "success"

    def test_purge_audit_logs_writes_heartbeat(self, db):
        call_command("purge_audit_logs")
        h = CronHeartbeat.objects.get(job_name="purge_audit_logs")
        assert h.last_status == "success"
