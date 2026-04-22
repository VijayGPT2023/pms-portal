"""Run Django migrations on DirectAdmin shared hosting.

Usage: Setup Python App → Manage → "Execute python script" → paste the full path:
       /home/npcindia/pms_app/run_migrate.py
       then click ▶ Run Script.

This creates all 38 core tables + Django's auth/session tables in MariaDB.
Safe to run multiple times — Django tracks applied migrations in django_migrations.
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
print("Running Django migrations against MariaDB...")
print("=" * 60)
call_command('migrate', verbosity=2)
print("=" * 60)
print("Migrations complete.")
print("=" * 60)
