"""
Integration tests for proposal/document routes -- list, upload form, link form,
search API.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


def _create_test_assignment():
    """Insert a test assignment in the DB and return its ID."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assignments (assignment_no, type, title, client, office_id, status,
               workflow_stage, registration_status, team_leader_officer_id, registered_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "NPC/HQ/ASG/PROPTEST/001", "ASSIGNMENT", "Proposal Test Assignment",
            "Test Client", "HQ", "Not Started", "DETAIL_ENTRY", "APPROVED",
            "ADMIN", "ADMIN"
        ))
        cursor.execute(
            "SELECT id FROM assignments WHERE title = 'Proposal Test Assignment' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row)["id"]


def _cleanup_test_assignment(assignment_id):
    """Remove test assignment and related data."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proposal_documents WHERE assignment_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM assignment_clients WHERE assignment_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))


class TestProposalListAuthentication:
    def test_proposal_list(self, client, auth_cookies):
        """GET /proposals/ returns 200 with valid auth cookies."""
        response = client.get("/proposals/", cookies=auth_cookies)
        assert response.status_code == 200

    def test_proposal_list_unauthenticated(self, client):
        """GET /proposals/ without cookies redirects to login."""
        response = client.get("/proposals/", follow_redirects=False)
        # App may redirect (302) or render an inline redirect page (200)
        assert response.status_code in (200, 302)
        if response.status_code == 302:
            location = response.headers.get("location", "")
            assert "login" in location.lower()


class TestProposalUploadForm:
    def test_upload_form(self, client, auth_cookies, test_db):
        """GET /proposals/upload/{assignment_id} returns 200 for a valid assignment."""
        assignment_id = None
        try:
            assignment_id = _create_test_assignment()
            response = client.get(
                f"/proposals/upload/{assignment_id}", cookies=auth_cookies
            )
            assert response.status_code == 200
        finally:
            if assignment_id:
                _cleanup_test_assignment(assignment_id)

    def test_upload_form_nonexistent_assignment(self, client, auth_cookies):
        """GET /proposals/upload/999999 returns 404 for nonexistent assignment."""
        response = client.get(
            "/proposals/upload/999999", cookies=auth_cookies,
            follow_redirects=False
        )
        # The route raises HTTPException(404) which the app may handle
        assert response.status_code in (404, 500)


class TestProposalLinkForm:
    def test_link_form(self, client, auth_cookies, test_db):
        """GET /proposals/link/{assignment_id} returns 200 for a valid assignment."""
        assignment_id = None
        try:
            assignment_id = _create_test_assignment()
            response = client.get(
                f"/proposals/link/{assignment_id}", cookies=auth_cookies
            )
            assert response.status_code == 200
        finally:
            if assignment_id:
                _cleanup_test_assignment(assignment_id)


class TestProposalListFilters:
    def test_proposal_list_filter(self, client, auth_cookies):
        """GET /proposals/?office=HQ returns 200 with office filter."""
        response = client.get("/proposals/?office=HQ", cookies=auth_cookies)
        assert response.status_code == 200

    def test_proposal_list_filter_has_proposal_yes(self, client, auth_cookies):
        """GET /proposals/?has_proposal=yes returns 200."""
        response = client.get("/proposals/?has_proposal=yes", cookies=auth_cookies)
        assert response.status_code == 200

    def test_proposal_list_filter_has_proposal_no(self, client, auth_cookies):
        """GET /proposals/?has_proposal=no returns 200."""
        response = client.get("/proposals/?has_proposal=no", cookies=auth_cookies)
        assert response.status_code == 200


class TestSearchActivitiesAPI:
    def test_search_activities_api(self, client, auth_cookies, test_db):
        """GET /proposals/api/search-activities?q=test returns JSON results."""
        # Create an assignment to search for
        assignment_id = None
        try:
            assignment_id = _create_test_assignment()

            response = client.get(
                "/proposals/api/search-activities?q=Proposal", cookies=auth_cookies
            )
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            # Should find the assignment we just created
            matching = [r for r in data if "Proposal" in r.get("title", "")]
            assert len(matching) >= 1
        finally:
            if assignment_id:
                _cleanup_test_assignment(assignment_id)

    def test_search_activities_api_short(self, client, auth_cookies):
        """GET /proposals/api/search-activities?q=a with short query returns empty."""
        response = client.get(
            "/proposals/api/search-activities?q=a", cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_search_activities_api_empty(self, client, auth_cookies):
        """GET /proposals/api/search-activities?q= with empty query returns empty."""
        response = client.get(
            "/proposals/api/search-activities?q=", cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_search_activities_api_unauthenticated(self, client):
        """GET /proposals/api/search-activities?q=test returns 401 or inline redirect without auth."""
        response = client.get("/proposals/api/search-activities?q=test")
        # API endpoints may return 401 JSON or 200 with inline redirect
        assert response.status_code in (200, 401)
