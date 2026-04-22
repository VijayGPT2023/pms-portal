"""Collect static files into staticfiles/ for WhiteNoise to serve.

Usage: Setup Python App → Manage → "Execute python script" → paste the full path:
       /home/npcindia/pms_app/run_collectstatic.py
       then click ▶ Run Script.

Run this once after initial deploy, and again any time you change CSS/JS/images.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import pymysql
    pymysql.install_as_MySQLdb()
    import MySQLdb
    MySQLdb.version_info = (2, 2, 4, 'final', 0)
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pms_portal.settings')

import django  # noqa: E402
django.setup()

from django.core.management import call_command  # noqa: E402

print("=" * 60)
print("Collecting static files for WhiteNoise...")
print("=" * 60)
call_command('collectstatic', interactive=False, verbosity=2, clear=True)
print("=" * 60)
print("Static files ready. Restart the app in DirectAdmin.")
print("=" * 60)
