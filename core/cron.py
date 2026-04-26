"""
Cron heartbeat helper (M0-OPS-08, M0-REL-13).

Wrap any management command body with:

    from core.cron import heartbeat

    with heartbeat("backup_db", expected_interval_seconds=86400):
        # do the work
        ...

The context manager updates the CronHeartbeat row with start time, end time,
duration, status, and error message. Admin dashboard reads these to show
red/amber/green per job.
"""
import logging
import time
from contextlib import contextmanager

from django.utils import timezone


logger = logging.getLogger(__name__)


@contextmanager
def heartbeat(job_name, expected_interval_seconds=86400):
    """
    Context manager that records a cron-job run in CronHeartbeat.

    On exception:
      - last_status = 'failure'
      - last_error  = repr(exc)
      - exception is re-raised so the cron itself reports failure too
    """
    # Avoid import-time circular: pull model lazily.
    from core.models import CronHeartbeat

    started = time.monotonic()
    obj, _ = CronHeartbeat.objects.update_or_create(
        job_name=job_name,
        defaults={
            "last_status": CronHeartbeat.Status.RUNNING,
            "last_run_at": timezone.now(),
            "expected_interval_seconds": expected_interval_seconds,
        },
    )
    try:
        yield obj
    except BaseException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        CronHeartbeat.objects.filter(pk=obj.pk).update(
            last_status=CronHeartbeat.Status.FAILURE,
            last_error=repr(exc)[:1000],
            last_duration_ms=duration_ms,
            last_run_at=timezone.now(),
        )
        logger.exception("cron job %s failed", job_name)
        raise
    else:
        duration_ms = int((time.monotonic() - started) * 1000)
        CronHeartbeat.objects.filter(pk=obj.pk).update(
            last_status=CronHeartbeat.Status.SUCCESS,
            last_error="",
            last_duration_ms=duration_ms,
            last_run_at=timezone.now(),
        )
