"""Create the initial admin Officer on DirectAdmin.

Usage: Setup Python App → Manage → "Execute python script" → paste the full path:
       /home/npcindia/pms_app/run_createsuperuser.py
       then click ▶ Run Script.

Creates:
    email:       admin@npcindia.gov.in
    officer_id:  ADMIN
    password:    admin123   ← change immediately after first login

Safe to run multiple times — skips creation if an Officer with this email already exists.
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

from django.contrib.auth import get_user_model  # noqa: E402

Officer = get_user_model()

ADMIN_EMAIL = "admin@npcindia.gov.in"
ADMIN_OFFICER_ID = "ADMIN"
ADMIN_NAME = "Portal Administrator"
ADMIN_PASSWORD = "admin123"

if Officer.objects.filter(email=ADMIN_EMAIL).exists():
    print(f"Admin already exists: {ADMIN_EMAIL} (no action taken).")
else:
    Officer.objects.create_superuser(
        email=ADMIN_EMAIL,
        officer_id=ADMIN_OFFICER_ID,
        name=ADMIN_NAME,
        password=ADMIN_PASSWORD,
    )
    print("=" * 60)
    print(f"Admin created.")
    print(f"  Email:    {ADMIN_EMAIL}")
    print(f"  Password: {ADMIN_PASSWORD}")
    print("  CHANGE THIS PASSWORD IMMEDIATELY after first login.")
    print("=" * 60)
