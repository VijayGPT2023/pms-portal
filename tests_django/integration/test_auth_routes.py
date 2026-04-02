"""
Integration tests for authentication routes.
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestLoginPage:
    def test_login_page_loads(self):
        client = TestClient()
        response = client.get("/login/")
        assert response.status_code == 200
        assert b"PMS Portal" in response.content
        assert b"Sign In" in response.content

    def test_login_redirects_if_authenticated(self, auth_client):
        response = auth_client.get("/login/")
        assert response.status_code == 302
        assert "/dashboard/" in response.url

    def test_login_with_valid_credentials(self, admin_user):
        client = TestClient()
        response = client.post("/login/", {
            "email": "admin@test.gov.in",
            "password": "testpass123",
        })
        assert response.status_code == 302
        assert "/dashboard/" in response.url

    def test_login_with_invalid_password(self, admin_user):
        client = TestClient()
        response = client.post("/login/", {
            "email": "admin@test.gov.in",
            "password": "wrongpass",
        })
        assert response.status_code == 200
        assert b"Invalid" in response.content

    def test_login_with_nonexistent_email(self):
        client = TestClient()
        response = client.post("/login/", {
            "email": "nobody@test.gov.in",
            "password": "pass",
        })
        assert response.status_code == 200
        assert b"Invalid" in response.content


class TestLogout:
    def test_logout_redirects(self, auth_client):
        response = auth_client.get("/logout/")
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_after_logout_cannot_access_dashboard(self, auth_client):
        auth_client.get("/logout/")
        response = auth_client.get("/dashboard/")
        assert response.status_code == 302  # Redirected to login


class TestRootRedirect:
    def test_root_unauthenticated_redirects_to_login(self):
        client = TestClient()
        response = client.get("/")
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_root_authenticated_redirects_to_dashboard(self, auth_client):
        response = auth_client.get("/")
        assert response.status_code == 302
        assert "/dashboard/" in response.url
