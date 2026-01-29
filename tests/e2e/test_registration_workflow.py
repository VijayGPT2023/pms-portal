"""
E2E tests for the full registration workflow journey:
Register -> Approve -> Assign TL -> Fill Details -> Verify
"""
import os
import sys
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestRegistrationWorkflow:
    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_full_registration_to_approval(self, base_url):
        """Register an assignment, approve it, assign TL."""
        session = self._login(base_url)

        # Step 1: Register
        response = session.post(
            f"{base_url}/assignment/register",
            data={
                "title": "E2E Full Workflow Test",
                "type": "ASSIGNMENT",
                "client": "E2E Corp",
                "description": "End to end test",
            },
            allow_redirects=True,
        )
        assert response.status_code == 200

        # Find the assignment ID
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, registration_status, workflow_stage FROM assignments WHERE title = ?",
                ("E2E Full Workflow Test",),
            )
            row = cursor.fetchone()
            assert row is not None
            data = dict(row)
            aid = data["id"]
            assert data["registration_status"] == "PENDING_APPROVAL"
            assert data["workflow_stage"] == "REGISTRATION"

        try:
            # Step 2: Approve registration
            response = session.post(
                f"{base_url}/approvals/registration/{aid}/approve",
                allow_redirects=True,
            )
            assert response.status_code == 200

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT registration_status, workflow_stage FROM assignments WHERE id = ?", (aid,))
                data = dict(cursor.fetchone())
                assert data["registration_status"] == "APPROVED"
                assert data["workflow_stage"] == "TL_ASSIGNMENT"

            # Step 3: Assign TL
            response = session.post(
                f"{base_url}/approvals/allocate-tl/{aid}",
                data={"team_leader_id": "ADMIN"},
                allow_redirects=True,
            )
            assert response.status_code == 200

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT team_leader_officer_id, workflow_stage FROM assignments WHERE id = ?", (aid,))
                data = dict(cursor.fetchone())
                assert data["team_leader_officer_id"] == "ADMIN"
                assert data["workflow_stage"] == "DETAIL_ENTRY"

            # Step 4: View assignment
            response = session.get(f"{base_url}/assignment/view/{aid}")
            assert response.status_code == 200
            assert "E2E Full Workflow Test" in response.text

        finally:
            # Cleanup
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM assignment_team WHERE assignment_id = ?", (aid,))
                cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (aid,))
                cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (aid,))
                cursor.execute("DELETE FROM assignments WHERE id = ?", (aid,))

    def test_register_development_work(self, base_url):
        """Register a development work and verify it is created correctly."""
        session = self._login(base_url)

        response = session.post(
            f"{base_url}/assignment/register",
            data={
                "title": "E2E Dev Work",
                "type": "DEVELOPMENT",
                "client": "Internal",
            },
            allow_redirects=True,
        )
        assert response.status_code == 200

        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assignments WHERE title = 'E2E Dev Work'")
            row = cursor.fetchone()
            assert row is not None
            data = dict(row)
            assert data["type"] == "DEVELOPMENT"

            # Cleanup
            cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (data["id"],))
            cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (data["id"],))
            cursor.execute("DELETE FROM assignments WHERE id = ?", (data["id"],))


class TestPermissionBoundaries:
    def test_unauthenticated_cannot_register(self, base_url):
        """Without login, registration should redirect to login."""
        session = requests.Session()
        response = session.get(f"{base_url}/assignment/register", allow_redirects=False)
        assert response.status_code == 302

    def test_unauthenticated_cannot_view_dashboard(self, base_url):
        session = requests.Session()
        response = session.get(f"{base_url}/dashboard", allow_redirects=False)
        assert response.status_code == 302

    def test_unauthenticated_cannot_approve(self, base_url):
        session = requests.Session()
        response = session.post(
            f"{base_url}/approvals/registration/1/approve",
            allow_redirects=False,
        )
        assert response.status_code == 302
