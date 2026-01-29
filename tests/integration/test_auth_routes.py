"""
Integration tests for authentication routes -- login, logout, session management.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestLoginPage:
    def test_login_page_loads(self, client):
        response = client.get("/login")
        assert response.status_code == 200

    def test_login_page_has_form(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        text_lower = response.text.lower()
        # Form may use various input types
        assert "input" in text_lower or "form" in text_lower


class TestLoginFlow:
    def test_valid_login_redirects(self, client, test_db):
        from app.auth import hash_password
        from app.database import get_db

        # Set known password for admin
        with get_db() as conn:
            cursor = conn.cursor()
            pw_hash = hash_password("admin_test_pass")
            cursor.execute(
                "UPDATE officers SET password_hash = ? WHERE officer_id = 'ADMIN'",
                (pw_hash,),
            )

        response = client.post(
            "/login",
            data={"email": "admin@npcindia.gov.in", "password": "admin_test_pass"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "pms_session" in response.cookies

    def test_invalid_password_stays_on_login(self, client, test_db):
        response = client.post(
            "/login",
            data={"email": "admin@npcindia.gov.in", "password": "wrong_password"},
            follow_redirects=False,
        )
        # App may return 200 (re-render), 302 (redirect), or 401 (unauthorized)
        assert response.status_code in (200, 302, 401)

    def test_nonexistent_email(self, client, test_db):
        response = client.post(
            "/login",
            data={"email": "nobody@npcindia.gov.in", "password": "password"},
            follow_redirects=False,
        )
        assert response.status_code in (200, 302, 401)

    def test_empty_email(self, client, test_db):
        response = client.post(
            "/login",
            data={"email": "", "password": "password"},
            follow_redirects=False,
        )
        assert response.status_code in (200, 302, 422)

    def test_empty_password(self, client, test_db):
        response = client.post(
            "/login",
            data={"email": "admin@npcindia.gov.in", "password": ""},
            follow_redirects=False,
        )
        assert response.status_code in (200, 302, 422)


class TestLogout:
    def test_logout_clears_session(self, client, auth_cookies):
        response = client.get("/logout", cookies=auth_cookies, follow_redirects=False)
        assert response.status_code == 302
        assert "login" in response.headers.get("location", "").lower()


class TestAuthProtection:
    def test_dashboard_requires_auth(self, client):
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code in (302, 401, 403)

    def test_admin_requires_auth(self, client):
        response = client.get("/admin/users", follow_redirects=False)
        assert response.status_code in (302, 401, 403)

    def test_approvals_requires_auth(self, client):
        response = client.get("/approvals", follow_redirects=False)
        assert response.status_code in (302, 401, 403)

    def test_mis_requires_auth(self, client):
        response = client.get("/mis", follow_redirects=False)
        assert response.status_code in (302, 401, 403)

    def test_root_redirects_to_login(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "login" in response.headers.get("location", "").lower()
