"""
backup_files — tarball the uploads directory (M0-REL-02).

Output: <BACKUP_DIR>/files_<YYYY-MM-DD_HHMMSS>.tar.gz

Source: settings.MEDIA_ROOT (which on DirectAdmin lives under PERSIST_DIR
so it survives re-deploys).
"""
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _backup_dir():
    persist = Path(getattr(settings, "PERSIST_DIR", settings.BASE_DIR))
    return persist / "backups"


class Command(BaseCommand):
    help = "Tarball the uploads directory to a timestamped gzipped archive."

    def add_arguments(self, parser):
        parser.add_argument("--out-dir", default=None)
        parser.add_argument("--source", default=None,
                            help="Override source dir (default MEDIA_ROOT)")

    def handle(self, *args, **opts):
        out_dir = Path(opts["out_dir"]) if opts["out_dir"] else _backup_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        source = Path(opts["source"]) if opts["source"] else Path(settings.MEDIA_ROOT)

        if not source.exists():
            self.stdout.write(self.style.WARNING(
                f"Source directory does not exist yet: {source} (creating empty archive)"
            ))
            source.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        target = out_dir / f"files_{ts}.tar.gz"

        with tarfile.open(target, "w:gz") as tar:
            tar.add(source, arcname=source.name)

        if not target.exists() or target.stat().st_size == 0:
            raise CommandError(f"Backup archive is missing or empty: {target}")

        # Integrity: re-open and count entries
        with tarfile.open(target, "r:gz") as tar:
            entries = sum(1 for _ in tar.getmembers())

        size_mb = target.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f"Backup written: {target} ({size_mb:.2f} MB, {entries} entries)"
        ))
