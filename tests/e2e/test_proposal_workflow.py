"""
E2E tests for the Proposal document handling system.
Tests: proposal list view, proposal link modes (upload and link tabs).
"""
import os
import sys
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestProposalListView:
    """Test the proposal list view showing assignments with/without proposals."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_proposal_list_view(self, base_url):
        """Login -> View proposal list -> Verify assignment list shown."""
        session = self._login(base_url)
        from app.database import get_db

        assignment_id = None

        try:
            # Create an assignment so the list is non-empty
            session.post(
                f"{base_url}/assignment/register",
                data={
                    "title": "E2E Proposal List Test Assignment",
                    "type": "ASSIGNMENT",
                    "client": "Proposal Corp",
                },
                allow_redirects=True,
            )

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM assignments WHERE title = ?",
                    ("E2E Proposal List Test Assignment",),
                )
                row = cursor.fetchone()
                if row:
                    assignment_id = row["id"]

            # Step 1: View proposal list
            response = session.get(f"{base_url}/proposals/")
            assert response.status_code == 200
            text = response.text.lower()
            # The page should show assignment data
            assert "proposal" in text or "assignment" in text

            # Step 2: Filter by type
            response = session.get(f"{base_url}/proposals/?type=ASSIGNMENT")
            assert response.status_code == 200

            # Step 3: Filter by has_proposal = yes (likely empty for new data)
            response = session.get(f"{base_url}/proposals/?has_proposal=yes")
            assert response.status_code == 200

            # Step 4: Filter by has_proposal = no
            response = session.get(f"{base_url}/proposals/?has_proposal=no")
            assert response.status_code == 200

            # Step 5: Filter by office
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT office_id FROM offices LIMIT 1")
                office_row = cursor.fetchone()

            if office_row:
                response = session.get(
                    f"{base_url}/proposals/?office={office_row['office_id']}"
                )
                assert response.status_code == 200

        finally:
            if assignment_id:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM proposal_documents WHERE assignment_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

    def test_proposal_list_unauthenticated(self, base_url):
        """Unauthenticated access to proposal list should redirect to login."""
        session = requests.Session()
        response = session.get(f"{base_url}/proposals/", allow_redirects=False)
        assert response.status_code == 302


class TestProposalLinkModes:
    """Test the proposal link form: verify upload and link tabs exist."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_proposal_link_modes(self, base_url):
        """Login -> Go to link form -> Verify upload and link tabs exist."""
        session = self._login(base_url)
        from app.database import get_db

        assignment_id = None

        try:
            # Create an assignment to use for proposals
            session.post(
                f"{base_url}/assignment/register",
                data={
                    "title": "E2E Proposal Link Modes Test",
                    "type": "ASSIGNMENT",
                    "client": "Link Mode Corp",
                },
                allow_redirects=True,
            )

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM assignments WHERE title = ?",
                    ("E2E Proposal Link Modes Test",),
                )
                row = cursor.fetchone()
                assert row is not None
                assignment_id = row["id"]

            # Step 1: View the proposal link form
            response = session.get(f"{base_url}/proposals/link/{assignment_id}")
            assert response.status_code == 200
            text = response.text.lower()

            # Step 2: Verify both modes are present in the form
            # The form should have upload and link options
            assert "upload" in text
            assert "link" in text

            # Step 3: View the proposal upload form
            response = session.get(f"{base_url}/proposals/upload/{assignment_id}")
            assert response.status_code == 200
            upload_text = response.text.lower()
            assert "upload" in upload_text or "document" in upload_text

            # Step 4: Test the search activities API
            response = session.get(f"{base_url}/proposals/api/search-activities?q=E2E")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

            # Step 5: Test search with too-short query
            response = session.get(f"{base_url}/proposals/api/search-activities?q=E")
            assert response.status_code == 200
            assert response.json() == []

        finally:
            if assignment_id:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM proposal_documents WHERE assignment_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

    def test_proposal_upload_with_file(self, base_url):
        """Test actual file upload to the proposal system."""
        session = self._login(base_url)
        from app.database import get_db

        assignment_id = None

        try:
            # Create an assignment
            session.post(
                f"{base_url}/assignment/register",
                data={
                    "title": "E2E Proposal Upload File Test",
                    "type": "ASSIGNMENT",
                    "client": "Upload File Corp",
                },
                allow_redirects=True,
            )

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM assignments WHERE title = ?",
                    ("E2E Proposal Upload File Test",),
                )
                row = cursor.fetchone()
                assert row is not None
                assignment_id = row["id"]

            # Upload a test PDF-like file
            import io
            fake_pdf_content = b"%PDF-1.4 fake pdf content for testing"
            fake_file = io.BytesIO(fake_pdf_content)

            response = session.post(
                f"{base_url}/proposals/upload/{assignment_id}",
                files={"file": ("test_proposal.pdf", fake_file, "application/pdf")},
                data={
                    "document_type": "PROPOSAL",
                    "description": "E2E test proposal document",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Verify document was saved in DB
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, file_name, document_type, file_size FROM proposal_documents WHERE assignment_id = ?",
                    (assignment_id,),
                )
                doc_row = cursor.fetchone()
                assert doc_row is not None
                doc = dict(doc_row)
                assert doc["file_name"] == "test_proposal.pdf"
                assert doc["document_type"] == "PROPOSAL"
                assert doc["file_size"] > 0

                doc_id = doc["id"]

            # Delete the uploaded document
            response = session.post(
                f"{base_url}/proposals/delete/{doc_id}",
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Verify deletion
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM proposal_documents WHERE id = ?", (doc_id,))
                assert cursor.fetchone() is None

        finally:
            if assignment_id:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM proposal_documents WHERE assignment_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

                # Cleanup uploaded files
                from app.config import UPLOAD_DIR
                import shutil
                upload_path = UPLOAD_DIR / str(assignment_id)
                if upload_path.exists():
                    shutil.rmtree(upload_path, ignore_errors=True)
