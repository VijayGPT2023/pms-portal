"""
check_heartbeats — email admins if any cron job is overdue
(M0-OPS-08, M0-REL-13).

Runs once per hour via cron. For each CronHeartbeat row, if last_run_at is
older than 1.5x the expected_interval_seconds, the job is reported overdue.

Output: list of overdue jobs to stdout + mail_admins (best-effort).

Usage:
    python manage.py check_heartbeats
"""
from django.core.mail import mail_admins
from django.core.management.base import BaseCommand

from core.models import CronHeartbeat


class Command(BaseCommand):
    help = "Report cron heartbeats that are overdue; email admins on any failure."

    def handle(self, *args, **opts):
        overdue = []
        failed = []
        all_jobs = list(CronHeartbeat.objects.all())

        for j in all_jobs:
            if j.is_overdue():
                overdue.append(j)
            elif j.last_status == CronHeartbeat.Status.FAILURE:
                failed.append(j)

        for j in all_jobs:
            tag = "OVERDUE" if j in overdue else ("FAILED" if j in failed else "OK")
            self.stdout.write(f"  [{tag}] {j.job_name} last_run={j.last_run_at} status={j.last_status}")

        if overdue or failed:
            body_lines = ["Cron heartbeat alert from PMS Portal:\n"]
            for j in overdue:
                body_lines.append(
                    f"  OVERDUE: {j.job_name} — last ran {j.last_run_at} "
                    f"(expected every {j.expected_interval_seconds}s)"
                )
            for j in failed:
                body_lines.append(
                    f"  FAILED:  {j.job_name} — error: {j.last_error[:200]}"
                )
            try:
                mail_admins(
                    f"[PMS] Cron alert: {len(overdue)} overdue, {len(failed)} failed",
                    "\n".join(body_lines),
                    fail_silently=True,
                )
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(all_jobs)} jobs total: {len(overdue)} overdue, {len(failed)} failed."
        ))
