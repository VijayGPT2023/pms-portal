"""
cleanup_backups — delete backup files older than retention window (M0-REL-03).

Retention is read from settings.BACKUP_RETENTION_DAYS (default 30).
Override per-run with --days.

Operates on <BACKUP_DIR>/db_*.gz and <BACKUP_DIR>/files_*.tar.gz —
will not delete unrelated files.
"""
import time
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _backup_dir():
    persist = Path(getattr(settings, "PERSIST_DIR", settings.BASE_DIR))
    return persist / "backups"


PATTERNS = ("db_*.gz", "files_*.tar.gz")


class Command(BaseCommand):
    help = "Delete backup files older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=None,
            help="Override retention days (default: settings.BACKUP_RETENTION_DAYS or 30)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List what would be deleted without deleting.",
        )

    def handle(self, *args, **opts):
        from core.cron import heartbeat
        with heartbeat("cleanup_backups", expected_interval_seconds=86400):
            self._do(opts)

    def _do(self, opts):
        days = opts["days"] if opts["days"] is not None else getattr(settings, "BACKUP_RETENTION_DAYS", 30)
        cutoff = time.time() - days * 86400
        out_dir = _backup_dir()
        if not out_dir.exists():
            self.stdout.write(f"Backup dir does not exist: {out_dir} — nothing to clean")
            return

        deleted = 0
        kept = 0
        for pattern in PATTERNS:
            for path in out_dir.glob(pattern):
                if path.stat().st_mtime < cutoff:
                    if opts["dry_run"]:
                        self.stdout.write(f"  WOULD DELETE: {path.name}")
                    else:
                        path.unlink()
                        self.stdout.write(f"  deleted: {path.name}")
                    deleted += 1
                else:
                    kept += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. {'Would delete' if opts['dry_run'] else 'Deleted'} {deleted} files; kept {kept} within {days}-day window."
        ))
