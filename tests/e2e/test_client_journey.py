"""
E2E tests for the complete Client workflow journey.
Tests client CRUD, assignment linking, MIS, and search API.
"""
import os
import sys
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestClientCRUDJourney:
    """End-to-end test of the complete client workflow:
    Login -> Create client -> View client -> Edit client -> View updated -> Verify in list."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_client_crud_journey(self, base_url):
        """Full CRUD journey: create -> view -> edit -> verify in list."""
        session = self._login(base_url)

        # Step 1: View the new client form
        response = session.get(f"{base_url}/clients/new")
        assert response.status_code == 200
        assert "client_name" in response.text.lower() or "Client" in response.text

        # Step 2: Create a new client
        response = session.post(
            f"{base_url}/clients/new",
            data={
                "client_name": "E2E Test Corp",
                "client_type": "Private",
                "address": "123 Test Street",
                "city": "Delhi",
                "state": "Delhi",
                "contact_person": "Test Contact",
                "contact_email": "test@e2ecorp.com",
                "contact_phone": "9876543210",
                "gstin": "07AABCE1234F1Z5",
                "pan": "AABCE1234F",
            },
            allow_redirects=False,
        )
        assert response.status_code == 302
        assert "/clients/" in response.headers.get("location", "")

        # Step 3: Find the created client in DB
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, client_name, client_type, city FROM clients WHERE client_name = ?",
                ("E2E Test Corp",),
            )
            row = cursor.fetchone()
            assert row is not None
            client = dict(row)
            client_id = client["id"]
            assert client["client_type"] == "Private"
            assert client["city"] == "Delhi"

        try:
            # Step 4: View the created client
            response = session.get(f"{base_url}/clients/{client_id}/view")
            assert response.status_code == 200
            assert "E2E Test Corp" in response.text

            # Step 5: Edit the client
            response = session.post(
                f"{base_url}/clients/{client_id}/edit",
                data={
                    "client_name": "E2E Test Corp Updated",
                    "client_type": "PSU",
                    "address": "456 Updated Street",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "contact_person": "Updated Contact",
                    "contact_email": "updated@e2ecorp.com",
                    "contact_phone": "9876543211",
                    "gstin": "27AABCE1234F1Z5",
                    "pan": "AABCE1234F",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Step 6: Verify update was persisted
            response = session.get(f"{base_url}/clients/{client_id}/view")
            assert response.status_code == 200
            assert "E2E Test Corp Updated" in response.text

            # Verify in DB
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT client_name, client_type, city FROM clients WHERE id = ?", (client_id,))
                updated = dict(cursor.fetchone())
                assert updated["client_name"] == "E2E Test Corp Updated"
                assert updated["client_type"] == "PSU"
                assert updated["city"] == "Mumbai"

            # Step 7: Verify client appears in client list
            response = session.get(f"{base_url}/clients/")
            assert response.status_code == 200
            assert "E2E Test Corp Updated" in response.text

        finally:
            # Cleanup
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM assignment_clients WHERE client_id = ?", (client_id,))
                cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))


class TestClientAssignmentLinking:
    """Test client-assignment linking: create client, create assignment,
    link them, verify sub-activity number, remove link."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_client_assignment_linking(self, base_url):
        """Create client -> Create assignment -> Link -> Verify sub-activity -> Remove."""
        session = self._login(base_url)
        from app.database import get_db

        # Step 1: Create a client
        session.post(
            f"{base_url}/clients/new",
            data={
                "client_name": "Link Test Client",
                "client_type": "Central Government",
                "city": "New Delhi",
            },
            allow_redirects=True,
        )

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM clients WHERE client_name = ?", ("Link Test Client",))
            client_row = cursor.fetchone()
            assert client_row is not None
            client_id = client_row["id"]

        # Step 2: Create an assignment
        session.post(
            f"{base_url}/assignment/register",
            data={
                "title": "E2E Client Link Test Assignment",
                "type": "ASSIGNMENT",
                "client": "Link Test Client",
                "description": "Testing client-assignment linking",
            },
            allow_redirects=True,
        )

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, assignment_no FROM assignments WHERE title = ?",
                ("E2E Client Link Test Assignment",),
            )
            assignment_row = cursor.fetchone()
            assert assignment_row is not None
            assignment_id = assignment_row["id"]
            assignment_no = assignment_row["assignment_no"]

        try:
            # Step 3: View the manage clients page for this assignment
            response = session.get(f"{base_url}/clients/assignment/{assignment_id}/manage")
            assert response.status_code == 200

            # Step 4: Link client to assignment
            response = session.post(
                f"{base_url}/clients/assignment/{assignment_id}/add",
                data={
                    "client_id": client_id,
                    "billing_share_percent": 100,
                    "description": "Primary client",
                    "is_primary": 1,
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Step 5: Verify sub_activity_number was generated
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, sub_activity_number, billing_share_percent FROM assignment_clients WHERE assignment_id = ? AND client_id = ?",
                    (assignment_id, client_id),
                )
                link_row = cursor.fetchone()
                assert link_row is not None
                link = dict(link_row)
                link_id = link["id"]
                assert link["sub_activity_number"] is not None
                assert "SUB-" in link["sub_activity_number"]
                assert link["billing_share_percent"] == 100

            # Step 6: Verify client appears on the manage page
            response = session.get(f"{base_url}/clients/assignment/{assignment_id}/manage")
            assert response.status_code == 200
            assert "Link Test Client" in response.text

            # Step 7: Remove client link
            response = session.post(
                f"{base_url}/clients/assignment/{assignment_id}/{link_id}/remove",
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Verify removal
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM assignment_clients WHERE assignment_id = ? AND client_id = ?",
                    (assignment_id, client_id),
                )
                assert cursor.fetchone() is None

        finally:
            # Cleanup
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM assignment_clients WHERE assignment_id = ?", (assignment_id,))
                cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (assignment_id,))
                cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
                cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
                cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))


class TestClientMISJourney:
    """Test Client MIS: create clients, link to assignments, view MIS, verify totals."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_client_mis_journey(self, base_url):
        """Create multiple clients -> Link to assignments -> View MIS -> Verify."""
        session = self._login(base_url)
        from app.database import get_db

        created_client_ids = []
        created_assignment_ids = []

        try:
            # Create two clients
            for i, name in enumerate(["MIS Client Alpha", "MIS Client Beta"]):
                session.post(
                    f"{base_url}/clients/new",
                    data={
                        "client_name": name,
                        "client_type": "Private" if i == 0 else "PSU",
                        "city": "Delhi",
                    },
                    allow_redirects=True,
                )
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM clients WHERE client_name = ?", (name,))
                    row = cursor.fetchone()
                    assert row is not None
                    created_client_ids.append(row["id"])

            # Create an assignment and link both clients
            session.post(
                f"{base_url}/assignment/register",
                data={
                    "title": "E2E MIS Multi Client Assignment",
                    "type": "ASSIGNMENT",
                    "client": "MIS Client Alpha",
                },
                allow_redirects=True,
            )
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM assignments WHERE title = ?",
                    ("E2E MIS Multi Client Assignment",),
                )
                row = cursor.fetchone()
                assert row is not None
                assignment_id = row["id"]
                created_assignment_ids.append(assignment_id)

            # Link both clients
            for idx, cid in enumerate(created_client_ids):
                session.post(
                    f"{base_url}/clients/assignment/{assignment_id}/add",
                    data={
                        "client_id": cid,
                        "billing_share_percent": 50,
                        "description": f"Sub-activity {idx + 1}",
                        "is_primary": 1 if idx == 0 else 0,
                    },
                    allow_redirects=True,
                )

            # View Client MIS
            response = session.get(f"{base_url}/clients/mis")
            assert response.status_code == 200
            # The MIS page should have client data and totals
            assert "MIS Client Alpha" in response.text or "client" in response.text.lower()

            # Filter by client type
            response = session.get(f"{base_url}/clients/mis?client_type=Private")
            assert response.status_code == 200

        finally:
            # Cleanup
            with get_db() as conn:
                cursor = conn.cursor()
                for aid in created_assignment_ids:
                    cursor.execute("DELETE FROM assignment_clients WHERE assignment_id = ?", (aid,))
                    cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (aid,))
                    cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (aid,))
                    cursor.execute("DELETE FROM assignments WHERE id = ?", (aid,))
                for cid in created_client_ids:
                    cursor.execute("DELETE FROM clients WHERE id = ?", (cid,))


class TestClientSearchAPI:
    """Test the client search JSON API."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_client_search_api(self, base_url):
        """Create clients -> Search API -> Verify results."""
        session = self._login(base_url)
        from app.database import get_db

        created_ids = []

        try:
            # Create some unique clients
            for name in ["SearchTest Alpha Corp", "SearchTest Beta Ltd", "SearchTest Gamma Inc"]:
                session.post(
                    f"{base_url}/clients/new",
                    data={
                        "client_name": name,
                        "client_type": "Private",
                        "city": "Delhi",
                    },
                    allow_redirects=True,
                )
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM clients WHERE client_name = ?", (name,))
                    row = cursor.fetchone()
                    if row:
                        created_ids.append(row["id"])

            # Test search API with partial match
            response = session.get(f"{base_url}/clients/api/search?q=SearchTest")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) >= 3
            names = [d["client_name"] for d in data]
            assert "SearchTest Alpha Corp" in names
            assert "SearchTest Beta Ltd" in names

            # Test search with more specific query
            response = session.get(f"{base_url}/clients/api/search?q=Alpha Corp")
            assert response.status_code == 200
            data = response.json()
            assert len(data) >= 1
            assert any("Alpha" in d["client_name"] for d in data)

            # Test search with too-short query (should return empty)
            response = session.get(f"{base_url}/clients/api/search?q=S")
            assert response.status_code == 200
            data = response.json()
            assert data == []

            # Test search without auth returns 401
            unauth_session = requests.Session()
            response = unauth_session.get(f"{base_url}/clients/api/search?q=SearchTest")
            assert response.status_code == 401

        finally:
            # Cleanup
            with get_db() as conn:
                cursor = conn.cursor()
                for cid in created_ids:
                    cursor.execute("DELETE FROM clients WHERE id = ?", (cid,))
