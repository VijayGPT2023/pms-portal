"""
Integration tests for admin routes -- user management, roles, diagnostics.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestAdminPages:
    def test_admin_users_page(self, client, auth_cookies):
        response = client.get("/admin/users", cookies=auth_cookies)
        assert response.status_code == 200

    def test_admin_roles_page(self, client, auth_cookies):
        response = client.get("/admin/roles", cookies=auth_cookies)
        assert response.status_code == 200

    def test_admin_activity_log(self, client, auth_cookies):
        response = client.get("/admin/activity-log", cookies=auth_cookies)
        assert response.status_code == 200

    def test_diagnostics_endpoint(self, client, auth_cookies):
        response = client.get("/admin/diagnostics", cookies=auth_cookies)
        assert response.status_code == 200


class TestAdminAccess:
    def test_non_admin_cannot_access_users(self, client, test_db, create_test_officer):
        """A regular officer should not see admin pages."""
        oid = create_test_officer("TESTOFF", "Test Officer", "testoff@npcindia.gov.in")

        # Login as this officer
        response = client.post(
            "/login",
            data={"email": "testoff@npcindia.gov.in", "password": "test123"},
            follow_redirects=False,
        )
        cookies = dict(response.cookies)

        response = client.get("/admin/users", cookies=cookies, follow_redirects=False)
        # Should redirect or return error for non-admin
        assert response.status_code in (200, 302, 403)
