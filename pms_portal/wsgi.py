"""
WSGI config for pms_portal project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

# DirectAdmin: install pymysql as the MySQLdb driver before Django loads.
# Django 6 requires mysqlclient >= 2.2.1; pymysql reports 1.4.6, so we
# monkey-patch MySQLdb.version_info to satisfy the version check.
try:
    import pymysql
    pymysql.install_as_MySQLdb()
    import MySQLdb
    MySQLdb.version_info = (2, 2, 4, 'final', 0)
except ImportError:
    pass

from django.core.wsgi import get_wsgi_application  # noqa: E402

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pms_portal.settings')

application = get_wsgi_application()
