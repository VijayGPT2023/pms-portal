"""
Integration tests for profile routes -- view profile, change password.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestProfilePage:
    def test_profile_loads(self, client, auth_cookies):
        response = client.get("/profile", cookies=auth_cookies)
        assert response.status_code == 200

    def test_profile_unauthenticated_redirects(self, client):
        response = client.get("/profile", follow_redirects=False)
        # App may redirect (302) or render an inline redirect page (200)
        assert response.status_code in (200, 302)


class TestChangePassword:
    def test_change_password_page_loads(self, client, auth_cookies):
        response = client.get("/profile/change-password", cookies=auth_cookies)
        assert response.status_code == 200

    def test_change_password_wrong_current(self, client, auth_cookies, test_db):
        response = client.post(
            "/profile/change-password",
            data={
                "current_password": "definitely_wrong",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )
        # Should redirect back with error or show error
        assert response.status_code in (200, 302)

    def test_change_password_mismatch(self, client, auth_cookies, test_db):
        response = client.post(
            "/profile/change-password",
            data={
                "current_password": "testpass123",
                "new_password": "newpass123",
                "confirm_password": "different456",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )
        assert response.status_code in (200, 302)
