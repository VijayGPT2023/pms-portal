"""
restore_db — restore a gzipped DB backup produced by `backup_db` (M0-REL-06).

Engine-aware:
  * SQLite  → gunzip + replace the .sqlite3 file (with a safety side-copy first).
  * MariaDB → gunzip + pipe to `mysql` client.

Safety: --confirm is REQUIRED to actually execute. Without it, the command
prints what it WOULD do and exits non-zero. Always pre-flight via --target-db
into a sandbox before touching production.

Usage:
    # Dry run
    python manage.py restore_db /path/to/db_2026-04-26_020000.sql.gz

    # Execute on production (requires --confirm)
    python manage.py restore_db /path/to/db_2026-04-26_020000.sql.gz --confirm

    # Execute into a sandbox DB instead of the configured one
    python manage.py restore_db backup.sql.gz --target-db pms_sandbox --confirm
"""
import gzip
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restore a gzipped DB backup file (use --confirm to execute)."

    def add_arguments(self, parser):
        parser.add_argument("backup_file", help="Path to db_*.gz backup file")
        parser.add_argument("--confirm", action="store_true",
                            help="Actually execute the restore (without this it's a dry run)")
        parser.add_argument("--target-db", default=None,
                            help="Restore into this DB name instead of the configured one (MariaDB only)")

    def handle(self, *args, **opts):
        backup = Path(opts["backup_file"]).resolve()
        if not backup.exists():
            raise CommandError(f"Backup file not found: {backup}")
        engine = settings.DATABASES["default"]["ENGINE"]
        confirm = opts["confirm"]

        self.stdout.write(f"Backup file: {backup}")
        self.stdout.write(f"Engine: {engine}")

        if engine.endswith("sqlite3"):
            self._restore_sqlite(backup, confirm)
        elif "mysql" in engine:
            self._restore_mysql(backup, confirm, opts.get("target_db"))
        else:
            raise CommandError(f"Unsupported DB engine: {engine}")

        if confirm:
            self.stdout.write(self.style.SUCCESS(
                "Restore complete. Run `manage.py verify_restore` next to validate."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "DRY RUN. Re-run with --confirm to actually restore."
            ))

    def _restore_sqlite(self, backup, confirm):
        target = Path(settings.DATABASES["default"]["NAME"])
        side_copy = target.with_suffix(target.suffix + f".pre-restore-{datetime.now():%Y%m%d_%H%M%S}")
        self.stdout.write(f"Target SQLite file: {target}")
        self.stdout.write(f"Side-copy of current DB will be saved to: {side_copy}")
        if not confirm:
            return
        if target.exists():
            shutil.copy2(target, side_copy)
            self.stdout.write(f"  Side-copy written: {side_copy}")
        with gzip.open(backup, "rb") as f_in, open(target, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        self.stdout.write(f"  Restored {backup} -> {target}")

    def _restore_mysql(self, backup, confirm, target_db_override):
        cfg = settings.DATABASES["default"]
        db_name = target_db_override or cfg["NAME"]
        self.stdout.write(f"Target MariaDB: {cfg.get('USER')}@{cfg.get('HOST')}:{cfg.get('PORT')} db={db_name}")
        if not confirm:
            return
        cmd = [
            "mysql",
            "-h", cfg.get("HOST", "localhost"),
            "-P", str(cfg.get("PORT", 3306)),
            "-u", cfg["USER"],
            f"-p{cfg['PASSWORD']}",
            db_name,
        ]
        try:
            with gzip.open(backup, "rb") as f_in:
                proc = subprocess.run(cmd, input=f_in.read(),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      check=True)
        except FileNotFoundError:
            raise CommandError("mysql binary not found in PATH.")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")[:500]
            raise CommandError(f"mysql restore failed (exit {e.returncode}): {err}")
        self.stdout.write(f"  Restored {backup} into {db_name}")
