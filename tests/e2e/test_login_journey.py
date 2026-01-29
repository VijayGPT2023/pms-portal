"""
E2E tests for login journey -- uses requests (no browser needed).
For full Playwright tests, install playwright and use page fixtures.
"""
import os
import sys
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestLoginJourney:
    def test_login_page_accessible(self, base_url):
        response = requests.get(f"{base_url}/login")
        assert response.status_code == 200
        assert "PMS" in response.text or "Login" in response.text

    def test_login_and_access_dashboard(self, base_url):
        session = requests.Session()

        # Login
        response = session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
            allow_redirects=True,
        )
        assert response.status_code == 200
        assert "dashboard" in response.url.lower() or "Dashboard" in response.text

    def test_login_and_access_register(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )

        response = session.get(f"{base_url}/assignment/register")
        assert response.status_code == 200
        assert "ASSIGNMENT" in response.text
        assert "TRAINING" in response.text
        assert "DEVELOPMENT" in response.text

    def test_login_and_access_approvals(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )

        response = session.get(f"{base_url}/approvals")
        assert response.status_code == 200

    def test_login_and_logout(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )

        # Logout
        response = session.get(f"{base_url}/logout", allow_redirects=False)
        assert response.status_code == 302

        # Dashboard should now redirect to login
        response = session.get(f"{base_url}/dashboard", allow_redirects=False)
        assert response.status_code == 302

    def test_invalid_login_stays_on_login(self, base_url):
        session = requests.Session()
        response = session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "wrong"},
            allow_redirects=True,
        )
        assert "login" in response.url.lower() or "error" in response.text.lower()
