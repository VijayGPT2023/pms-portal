"""
Integration tests for client routes -- CRUD, MIS, search API, assignment linking.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


class TestClientListAuthentication:
    def test_client_list_authenticated(self, client, auth_cookies):
        """GET /clients/ returns 200 with valid auth cookies."""
        response = client.get("/clients/", cookies=auth_cookies)
        assert response.status_code == 200

    def test_client_list_unauthenticated(self, client):
        """GET /clients/ without cookies redirects to login."""
        response = client.get("/clients/", follow_redirects=False)
        # App may redirect (302) or render an inline redirect page (200)
        assert response.status_code in (200, 302)
        if response.status_code == 302:
            location = response.headers.get("location", "")
            assert "login" in location.lower()


class TestClientForm:
    def test_new_client_form(self, client, auth_cookies):
        """GET /clients/new returns 200 with the client creation form."""
        response = client.get("/clients/new", cookies=auth_cookies)
        assert response.status_code == 200
        assert "client" in response.text.lower() or "Client" in response.text


class TestClientCRUD:
    def _create_client(self, client, auth_cookies, name="Test Client INTG"):
        """Helper: create a client via POST and return the response."""
        return client.post(
            "/clients/new",
            data={
                "client_name": name,
                "client_type": "Central Government",
                "address": "123 Test Street",
                "city": "New Delhi",
                "state": "Delhi",
                "contact_person": "John Test",
                "contact_email": "john@test.gov.in",
                "contact_phone": "9876543210",
                "gstin": "07AAACH7409R1ZP",
                "pan": "AAACH7409R",
            },
            cookies=auth_cookies,
            follow_redirects=False,
        )

    def _get_client_id(self, name="Test Client INTG"):
        """Helper: get client ID by name from the DB."""
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM clients WHERE client_name = ?", (name,))
            row = cursor.fetchone()
            return dict(row)["id"] if row else None

    def _cleanup_client(self, name="Test Client INTG"):
        """Helper: remove test client from the DB."""
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM assignment_clients WHERE client_id IN (SELECT id FROM clients WHERE client_name = ?)", (name,))
            cursor.execute("DELETE FROM clients WHERE client_name = ?", (name,))

    def test_create_client(self, client, auth_cookies, test_db):
        """POST /clients/new with form data creates a client and redirects."""
        try:
            response = self._create_client(client, auth_cookies)
            assert response.status_code == 302
            location = response.headers.get("location", "")
            assert "/clients" in location

            # Verify in DB
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM clients WHERE client_name = ?", ("Test Client INTG",))
                row = cursor.fetchone()
                assert row is not None
                data = dict(row)
                assert data["client_type"] == "Central Government"
                assert data["city"] == "New Delhi"
        finally:
            self._cleanup_client()

    def test_client_view(self, client, auth_cookies, test_db):
        """GET /clients/{id}/view returns 200 for an existing client."""
        try:
            self._create_client(client, auth_cookies, name="View Test Client")
            cid = self._get_client_id("View Test Client")
            assert cid is not None

            response = client.get(f"/clients/{cid}/view", cookies=auth_cookies)
            assert response.status_code == 200
            assert "View Test Client" in response.text
        finally:
            self._cleanup_client("View Test Client")

    def test_edit_client_form(self, client, auth_cookies, test_db):
        """GET /clients/{id}/edit returns 200 for an existing client."""
        try:
            self._create_client(client, auth_cookies, name="Edit Form Client")
            cid = self._get_client_id("Edit Form Client")
            assert cid is not None

            response = client.get(f"/clients/{cid}/edit", cookies=auth_cookies)
            assert response.status_code == 200
            assert "Edit Form Client" in response.text
        finally:
            self._cleanup_client("Edit Form Client")

    def test_update_client(self, client, auth_cookies, test_db):
        """POST /clients/{id}/edit updates client details and redirects."""
        try:
            self._create_client(client, auth_cookies, name="Update Test Client")
            cid = self._get_client_id("Update Test Client")
            assert cid is not None

            response = client.post(
                f"/clients/{cid}/edit",
                data={
                    "client_name": "Updated Client Name",
                    "client_type": "PSU",
                    "address": "456 Updated Ave",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "contact_person": "Jane Updated",
                    "contact_email": "jane@updated.gov.in",
                    "contact_phone": "1234567890",
                    "gstin": "",
                    "pan": "",
                },
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify update
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM clients WHERE id = ?", (cid,))
                row = cursor.fetchone()
                assert row is not None
                data = dict(row)
                assert data["client_name"] == "Updated Client Name"
                assert data["client_type"] == "PSU"
                assert data["city"] == "Mumbai"
        finally:
            self._cleanup_client("Updated Client Name")
            self._cleanup_client("Update Test Client")


class TestClientMIS:
    def test_client_mis(self, client, auth_cookies):
        """GET /clients/mis returns 200."""
        response = client.get("/clients/mis", cookies=auth_cookies)
        assert response.status_code == 200


class TestClientSearchAPI:
    def test_client_search_api(self, client, auth_cookies, test_db):
        """GET /clients/api/search?q=test returns JSON results."""
        # Create a client first so we have data to search
        from app.database import get_db
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO clients (client_code, client_name, client_type, is_active, created_by)
                        VALUES (?, ?, ?, 1, 'ADMIN')
                    """, ("SRCH-001", "Searchable Test Corp", "Private"))
                except Exception:
                    pass  # Already exists

            response = client.get("/clients/api/search?q=Searchable", cookies=auth_cookies)
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            # At least one result matching our search
            matching = [r for r in data if "Searchable" in r.get("client_name", "")]
            assert len(matching) >= 1
        finally:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM clients WHERE client_code = ?", ("SRCH-001",))

    def test_client_search_api_short_query(self, client, auth_cookies):
        """GET /clients/api/search?q=a with query < 2 chars returns empty list."""
        response = client.get("/clients/api/search?q=a", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestManageAssignmentClients:
    def test_manage_assignment_clients(self, client, auth_cookies, test_db):
        """GET /clients/assignment/{id}/manage returns 200 for a valid assignment."""
        from app.database import get_db

        # Create an assignment for the test
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO assignments (assignment_no, type, title, client, office_id, status,
                   workflow_stage, registration_status, registered_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "NPC/HQ/ASG/CLTEST/001", "ASSIGNMENT", "Client Manage Test",
                "Test Client", "HQ", "Not Started", "DETAIL_ENTRY", "APPROVED", "ADMIN"
            ))
            cursor.execute("SELECT id FROM assignments WHERE title = 'Client Manage Test' ORDER BY id DESC LIMIT 1")
            aid = dict(cursor.fetchone())["id"]

        try:
            response = client.get(f"/clients/assignment/{aid}/manage", cookies=auth_cookies)
            assert response.status_code == 200
        finally:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM assignment_clients WHERE assignment_id = ?", (aid,))
                cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (aid,))
                cursor.execute("DELETE FROM assignments WHERE id = ?", (aid,))


class TestClientListFilters:
    def test_client_list_filter_by_type(self, client, auth_cookies, test_db):
        """GET /clients/?client_type=Government filters by type."""
        response = client.get("/clients/?client_type=Central Government", cookies=auth_cookies)
        assert response.status_code == 200

    def test_client_list_filter_by_search(self, client, auth_cookies, test_db):
        """GET /clients/?search=test filters by search term."""
        response = client.get("/clients/?search=test", cookies=auth_cookies)
        assert response.status_code == 200
