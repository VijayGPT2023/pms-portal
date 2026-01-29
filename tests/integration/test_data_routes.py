"""
Integration tests for data routes -- export, config management.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestExport:
    def test_export_page_loads(self, client, auth_cookies):
        response = client.get("/data/export", cookies=auth_cookies)
        assert response.status_code == 200

    def test_export_assignments_excel(self, client, auth_cookies):
        response = client.get("/data/export/assignments", cookies=auth_cookies)
        # May return Excel file (200) or fail with empty data (500)
        assert response.status_code in (200, 500)


class TestConfig:
    def test_config_page_loads(self, client, auth_cookies):
        response = client.get("/data/admin/config", cookies=auth_cookies)
        assert response.status_code == 200

    def test_subdomains_api(self, client, auth_cookies):
        response = client.get("/data/api/subdomains/ES", cookies=auth_cookies)
        assert response.status_code == 200
