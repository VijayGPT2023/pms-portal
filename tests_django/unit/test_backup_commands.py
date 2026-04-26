"""
F.2 — backup management commands tests (M0-REL-01, REL-02, REL-03, REL-14).
"""
import gzip
import tarfile
import time
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


class TestBackupDb:
    def test_backup_db_writes_gzipped_file(self, tmp_path):
        # The pytest-django default test DB is in-memory SQLite, which has
        # no file to copy. Make a real on-disk SQLite, point the test at it.
        from django.db import connection
        db_name = connection.settings_dict.get("NAME", "")
        if isinstance(db_name, str) and ("memory" in str(db_name) or db_name == ":memory:"):
            # Construct a tiny on-disk SQLite to back up
            real_db = tmp_path / "real.sqlite3"
            real_db.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
            from django.test import override_settings
            with override_settings(DATABASES={"default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(real_db),
            }}):
                out = StringIO()
                call_command("backup_db", out_dir=str(tmp_path), stdout=out)
        else:
            out = StringIO()
            call_command("backup_db", out_dir=str(tmp_path), stdout=out)

        files = list(tmp_path.glob("db_*.gz"))
        assert len(files) == 1
        assert files[0].stat().st_size > 0
        with gzip.open(files[0], "rb") as f:
            head = f.read(64)
        assert len(head) > 0
        assert "Backup written" in out.getvalue()


class TestBackupFiles:
    def test_backup_files_creates_archive(self, tmp_path):
        # Source dir with one file
        src = tmp_path / "uploads"
        src.mkdir()
        (src / "sample.txt").write_text("test content")

        out_dir = tmp_path / "out"
        call_command("backup_files", out_dir=str(out_dir), source=str(src))

        archives = list(out_dir.glob("files_*.tar.gz"))
        assert len(archives) == 1
        with tarfile.open(archives[0], "r:gz") as tar:
            names = [m.name for m in tar.getmembers() if m.isfile()]
        # Member path includes the source dir name
        assert any("sample.txt" in n for n in names)

    def test_backup_files_handles_missing_source(self, tmp_path):
        # Should warn but not crash
        out_dir = tmp_path / "out"
        call_command("backup_files", out_dir=str(out_dir),
                     source=str(tmp_path / "does_not_exist"))
        archives = list(out_dir.glob("files_*.tar.gz"))
        assert len(archives) == 1


class TestCleanupBackups:
    def _make_file(self, path, mtime_days_ago):
        path.write_bytes(b"dummy")
        ts = time.time() - mtime_days_ago * 86400
        import os
        os.utime(path, (ts, ts))

    def test_cleanup_deletes_files_older_than_retention(self, tmp_path, settings):
        settings.PERSIST_DIR = str(tmp_path)
        backups = tmp_path / "backups"
        backups.mkdir()
        # 5 old DB backups, 2 recent file backups
        for i in range(5):
            self._make_file(backups / f"db_old_{i}.gz", mtime_days_ago=40)
        self._make_file(backups / "files_recent.tar.gz", mtime_days_ago=5)

        out = StringIO()
        call_command("cleanup_backups", days=30, stdout=out)

        remaining = sorted(p.name for p in backups.iterdir())
        assert remaining == ["files_recent.tar.gz"]
        assert "Deleted 5 files" in out.getvalue()

    def test_cleanup_dry_run_does_not_delete(self, tmp_path, settings):
        settings.PERSIST_DIR = str(tmp_path)
        backups = tmp_path / "backups"
        backups.mkdir()
        self._make_file(backups / "db_old.gz", mtime_days_ago=100)

        out = StringIO()
        call_command("cleanup_backups", days=30, dry_run=True, stdout=out)

        assert (backups / "db_old.gz").exists()
        assert "WOULD DELETE" in out.getvalue()
        assert "Would delete 1 files" in out.getvalue()

    def test_cleanup_skips_unrelated_files(self, tmp_path, settings):
        settings.PERSIST_DIR = str(tmp_path)
        backups = tmp_path / "backups"
        backups.mkdir()
        self._make_file(backups / "important_note.txt", mtime_days_ago=100)
        self._make_file(backups / "db_old.gz", mtime_days_ago=100)

        call_command("cleanup_backups", days=30)

        assert (backups / "important_note.txt").exists()
        assert not (backups / "db_old.gz").exists()
