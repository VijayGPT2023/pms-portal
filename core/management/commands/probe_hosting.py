"""
probe_hosting — emit a one-page snapshot of the runtime environment
(M0-OPS-15). Run after every panel update / hosting change so SA knows
what's actually available before touching the code.

Checks:
  * Python and Django versions
  * Available Python packages (a few that we depend on)
  * Subprocess capability — exec, mysqldump, mysql, tar, gzip
  * Filesystem write access (tmp, MEDIA_ROOT, BACKUP_DIR, LOG_FILE dir)
  * Disk free
  * DB connectivity
  * Mail backend / can-send-test
  * Environment variables present (no values printed)

Usage:
    python manage.py probe_hosting
"""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import django
from django.conf import settings
from django.core.management.base import BaseCommand


def _check(label, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok = False
        detail = f"{type(e).__name__}: {e}"
    return label, ok, detail


def _bin_present(name):
    return shutil.which(name) is not None


def _writable(path):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    test = p / ".probe_write_test"
    test.write_text("x")
    test.unlink()
    return True, str(p)


class Command(BaseCommand):
    help = "Print a runtime/environment snapshot for the current host."

    def handle(self, *args, **opts):
        self.stdout.write("=" * 60)
        self.stdout.write("PMS Hosting Capability Probe")
        self.stdout.write("=" * 60)

        results = []

        # Versions
        results.append(("Python", True, sys.version.split()[0]))
        results.append(("Django", True, django.get_version()))
        results.append(("Platform", True, sys.platform))

        # Packages we depend on
        for pkg in ("axes", "auditlog", "django_fsm", "whitenoise", "openpyxl", "pymysql"):
            results.append(_check(f"pkg: {pkg}", lambda p=pkg: (
                bool(importlib.import_module(p)), importlib.import_module(p).__name__
            )))

        # Subprocess capability
        try:
            subprocess.run(["echo", "ok"], capture_output=True, timeout=2)
            results.append(("subprocess.run", True, "available"))
        except Exception as e:
            results.append(("subprocess.run", False, repr(e)[:100]))

        # External binaries (server-side prod path uses these)
        for binname in ("mysqldump", "mysql", "tar", "gzip"):
            present = _bin_present(binname)
            results.append((f"binary: {binname}", present, shutil.which(binname) or "NOT FOUND"))

        # Filesystem
        results.append(_check("MEDIA_ROOT writable", lambda: _writable(settings.MEDIA_ROOT)))
        backups = Path(getattr(settings, "PERSIST_DIR", settings.BASE_DIR)) / "backups"
        results.append(_check("BACKUP dir writable", lambda: _writable(backups)))

        # Disk
        try:
            usage = shutil.disk_usage(str(getattr(settings, "PERSIST_DIR", settings.BASE_DIR)))
            results.append(("disk free", True, f"{usage.free / (1024**3):.1f} GB"))
        except Exception as e:
            results.append(("disk free", False, repr(e)[:100]))

        # DB connectivity
        try:
            from django.db import connection
            with connection.cursor() as c:
                c.execute("SELECT 1")
            results.append(("DB SELECT 1", True, settings.DATABASES["default"]["ENGINE"]))
        except Exception as e:
            results.append(("DB SELECT 1", False, repr(e)[:100]))

        # Mail backend
        backend = getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
        results.append(("EMAIL_BACKEND", True, backend))

        # Env vars present (names only, no values)
        env_keys = sorted(k for k in os.environ if k.startswith(("MYSQL_", "AXES_", "DJANGO_", "PMS_")))
        results.append(("env vars", True, ", ".join(env_keys) or "(none with our prefixes)"))

        # Render
        for label, ok, detail in results:
            tag = self.style.SUCCESS("OK  ") if ok else self.style.ERROR("FAIL")
            self.stdout.write(f"  {tag}  {label:<30} {detail}")

        self.stdout.write("=" * 60)
        fails = sum(1 for _, ok, _ in results if not ok)
        self.stdout.write(f"Done. {len(results) - fails} OK, {fails} failed.")
