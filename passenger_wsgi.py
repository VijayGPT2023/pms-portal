"""Passenger WSGI entry point for DirectAdmin shared hosting.

Deployed at the subdomain `pms.npcindia.info`, so Django sees the request at `/`
and no SCRIPT_NAME manipulation is needed (unlike the biometric subfolder deploy).

DirectAdmin's "Setup Python App" reads:
    Application Startup File : passenger_wsgi.py
    Application Entry Point  : application
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# pymysql shim must run BEFORE Django imports its MySQL backend.
# Django 6 requires mysqlclient >= 2.2.1; pymysql reports 1.4.6, so we
# monkey-patch MySQLdb.version_info to satisfy the version check.
try:
    import pymysql
    pymysql.install_as_MySQLdb()
    import MySQLdb
    MySQLdb.version_info = (2, 2, 4, 'final', 0)
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pms_portal.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
