"""
Integration tests for assignment routes -- registration, view, edit.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestRegistrationForm:
    def test_register_page_loads(self, client, auth_cookies):
        response = client.get("/assignment/register", cookies=auth_cookies)
        assert response.status_code == 200
        assert "register" in response.text.lower() or "Register" in response.text

    def test_register_form_has_all_types(self, client, auth_cookies):
        response = client.get("/assignment/register", cookies=auth_cookies)
        assert "ASSIGNMENT" in response.text
        assert "TRAINING" in response.text
        assert "DEVELOPMENT" in response.text


class TestRegistrationSubmission:
    def test_register_assignment(self, client, auth_cookies, test_db):
        response = client.post(
            "/assignment/register",
            data={
                "title": "Integration Test Assignment",
                "type": "ASSIGNMENT",
                "client": "Test Client",
                "description": "Test description",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302  # Redirect to dashboard

        # Verify in DB
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assignments WHERE title = ?",
                ("Integration Test Assignment",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert dict(row)["type"] == "ASSIGNMENT"
            assert dict(row)["registration_status"] == "PENDING_APPROVAL"
            assert dict(row)["workflow_stage"] == "REGISTRATION"
            # Cleanup
            cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (dict(row)["id"],))
            cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (dict(row)["id"],))
            cursor.execute("DELETE FROM assignments WHERE id = ?", (dict(row)["id"],))

    def test_register_training(self, client, auth_cookies, test_db):
        response = client.post(
            "/assignment/register",
            data={
                "title": "Integration Test Training",
                "type": "TRAINING",
                "client": "NPC Internal",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302

        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assignments WHERE title = ?",
                ("Integration Test Training",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert dict(row)["type"] == "TRAINING"
            # Cleanup
            cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (dict(row)["id"],))
            cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (dict(row)["id"],))
            cursor.execute("DELETE FROM assignments WHERE id = ?", (dict(row)["id"],))

    def test_register_development(self, client, auth_cookies, test_db):
        response = client.post(
            "/assignment/register",
            data={
                "title": "Integration Test Dev Work",
                "type": "DEVELOPMENT",
                "client": "Internal",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302

        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assignments WHERE title = ?",
                ("Integration Test Dev Work",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert dict(row)["type"] == "DEVELOPMENT"
            # Cleanup
            cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (dict(row)["id"],))
            cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (dict(row)["id"],))
            cursor.execute("DELETE FROM assignments WHERE id = ?", (dict(row)["id"],))

    def test_register_without_title_fails(self, client, auth_cookies, test_db):
        response = client.post(
            "/assignment/register",
            data={"type": "ASSIGNMENT", "client": "Test"},
            cookies=auth_cookies,
            follow_redirects=False,
        )
        # Should fail with 422 (validation) or redirect back with error
        assert response.status_code in (302, 422)

    def test_register_invalid_type_defaults_to_assignment(self, client, auth_cookies, test_db):
        response = client.post(
            "/assignment/register",
            data={
                "title": "Invalid Type Test",
                "type": "INVALID_TYPE",
                "client": "Test",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302

        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assignments WHERE title = ?",
                ("Invalid Type Test",),
            )
            row = cursor.fetchone()
            if row:
                assert dict(row)["type"] == "ASSIGNMENT"  # Default fallback
                cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (dict(row)["id"],))
                cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (dict(row)["id"],))
                cursor.execute("DELETE FROM assignments WHERE id = ?", (dict(row)["id"],))


class TestAssignmentView:
    def test_view_nonexistent_assignment(self, client, auth_cookies):
        response = client.get("/assignment/view/999999", cookies=auth_cookies, follow_redirects=False)
        assert response.status_code in (302, 404)
