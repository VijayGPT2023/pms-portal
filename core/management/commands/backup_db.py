"""
backup_db — dump the database to a timestamped, gzipped file (M0-REL-01).

Engine-aware:
  * SQLite  → copy the .sqlite3 file + gzip.
  * MariaDB / MySQL → shell out to mysqldump + gzip.

Output: <BACKUP_DIR>/db_<YYYY-MM-DD_HHMMSS>.sql.gz (MariaDB)
        <BACKUP_DIR>/db_<YYYY-MM-DD_HHMMSS>.sqlite3.gz (dev)

Includes a basic integrity check (M0-REL-14):
  * File exists and is non-empty
  * Gzip header is valid
  * For MariaDB: contains at least one CREATE TABLE statement
"""
import gzip
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _backup_dir():
    persist = Path(getattr(settings, "PERSIST_DIR", settings.BASE_DIR))
    return persist / "backups"


class Command(BaseCommand):
    help = "Dump the database to a timestamped gzipped file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out-dir", default=None,
            help="Override backup directory (default: PERSIST_DIR/backups)",
        )

    def handle(self, *args, **opts):
        from core.cron import heartbeat
        with heartbeat("backup_db", expected_interval_seconds=86400):
            out_dir = Path(opts["out_dir"]) if opts["out_dir"] else _backup_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            engine = settings.DATABASES["default"]["ENGINE"]

            if engine.endswith("sqlite3"):
                target = out_dir / f"db_{ts}.sqlite3.gz"
                self._backup_sqlite(target)
            elif "mysql" in engine:
                target = out_dir / f"db_{ts}.sql.gz"
                self._backup_mysql(target)
            else:
                raise CommandError(f"Unsupported DB engine: {engine}")

            self._integrity_check(target, engine)
            size_mb = target.stat().st_size / (1024 * 1024)
            self.stdout.write(self.style.SUCCESS(
                f"Backup written: {target} ({size_mb:.2f} MB)"
            ))

    def _backup_sqlite(self, target):
        src = Path(settings.DATABASES["default"]["NAME"])
        if not src.exists():
            raise CommandError(f"SQLite file not found: {src}")
        with open(src, "rb") as f_in, gzip.open(target, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    def _backup_mysql(self, target):
        cfg = settings.DATABASES["default"]
        cmd = [
            "mysqldump",
            "-h", cfg.get("HOST", "localhost"),
            "-P", str(cfg.get("PORT", 3306)),
            "-u", cfg["USER"],
            f"-p{cfg['PASSWORD']}",
            "--single-transaction",
            "--routines",
            "--triggers",
            cfg["NAME"],
        ]
        try:
            with gzip.open(target, "wb") as f_out:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                f_out.write(proc.stdout)
        except FileNotFoundError:
            raise CommandError(
                "mysqldump binary not found. On DirectAdmin it's usually at "
                "/usr/bin/mysqldump — set PATH or use absolute path."
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")[:500]
            raise CommandError(f"mysqldump failed (exit {e.returncode}): {err}")

    def _integrity_check(self, target, engine):
        """Basic post-backup verification (M0-REL-14)."""
        if not target.exists() or target.stat().st_size == 0:
            raise CommandError(f"Backup file is missing or empty: {target}")
        # Gzip header check + content sniff
        try:
            with gzip.open(target, "rb") as f:
                head = f.read(4096)
        except Exception as e:
            raise CommandError(f"Backup file is not valid gzip: {e}")
        if "mysql" in engine and b"CREATE TABLE" not in head:
            # mysqldump puts CREATE TABLE near top; if absent, likely empty/failed
            self.stdout.write(self.style.WARNING(
                f"Integrity warning: no CREATE TABLE seen in first 4KB of {target.name}"
            ))
