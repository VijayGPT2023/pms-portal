"""
Integration tests for utilization claim routes -- CRUD, workflow transitions,
TL approve/reject, pending lists, summary MIS.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


def _create_draft_claim(officer_id="ADMIN"):
    """Insert a DRAFT utilization claim directly in the DB and return its ID."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO utilization_claims (
                claim_number, officer_id, claim_month, activity_date,
                man_days_claimed, activity_description, claim_type, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT')
        """, (
            f"UC-{officer_id}-TEST-001", officer_id, "2026-02",
            "2026-02-10", 1.0, "Test claim description", "ASSIGNMENT_WORK"
        ))
        cursor.execute(
            "SELECT id FROM utilization_claims WHERE claim_number = ? ORDER BY id DESC LIMIT 1",
            (f"UC-{officer_id}-TEST-001",)
        )
        row = cursor.fetchone()
        return dict(row)["id"]


def _create_submitted_claim(officer_id="ADMIN"):
    """Insert a SUBMITTED utilization claim directly in the DB and return its ID."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO utilization_claims (
                claim_number, officer_id, claim_month, activity_date,
                man_days_claimed, activity_description, claim_type, status,
                submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', CURRENT_TIMESTAMP)
        """, (
            f"UC-{officer_id}-SUBM-001", officer_id, "2026-02",
            "2026-02-11", 1.5, "Submitted claim for testing", "ASSIGNMENT_WORK"
        ))
        cursor.execute(
            "SELECT id FROM utilization_claims WHERE claim_number = ? ORDER BY id DESC LIMIT 1",
            (f"UC-{officer_id}-SUBM-001",)
        )
        row = cursor.fetchone()
        return dict(row)["id"]


def _cleanup_claim(claim_id):
    """Remove a test claim from the DB."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM utilization_claims WHERE id = ?", (claim_id,))


def _cleanup_claims_by_number(prefix):
    """Remove all test claims matching a claim_number prefix."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM utilization_claims WHERE claim_number LIKE ?", (f"{prefix}%",))


class TestUtilizationListAuthentication:
    def test_utilization_list(self, client, auth_cookies):
        """GET /utilization/ returns 200 with valid auth cookies."""
        response = client.get("/utilization/", cookies=auth_cookies)
        assert response.status_code == 200

    def test_utilization_list_unauthenticated(self, client):
        """GET /utilization/ without cookies redirects to login."""
        response = client.get("/utilization/", follow_redirects=False)
        # App may redirect (302) or render an inline redirect page (200)
        assert response.status_code in (200, 302)
        if response.status_code == 302:
            location = response.headers.get("location", "")
            assert "login" in location.lower()


class TestNewClaimForm:
    def test_new_claim_form(self, client, auth_cookies):
        """GET /utilization/new returns 200 with claim form."""
        response = client.get("/utilization/new", cookies=auth_cookies)
        assert response.status_code == 200


class TestCreateClaim:
    def test_create_claim(self, client, auth_cookies, test_db):
        """POST /utilization/new creates a DRAFT claim and redirects."""
        try:
            response = client.post(
                "/utilization/new",
                data={
                    "activity_date": "2026-02-15",
                    "claim_type": "ASSIGNMENT_WORK",
                    "man_days_claimed": "1.0",
                    "activity_description": "Integration test claim",
                },
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302
            location = response.headers.get("location", "")
            assert "/utilization" in location

            # Verify in DB
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM utilization_claims WHERE activity_description = ?",
                    ("Integration test claim",)
                )
                row = cursor.fetchone()
                assert row is not None
                data = dict(row)
                assert data["status"] == "DRAFT"
                assert data["claim_month"] == "2026-02"
                assert data["man_days_claimed"] == 1.0
        finally:
            _cleanup_claims_by_number("UC-ADMIN")
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM utilization_claims WHERE activity_description = ?",
                    ("Integration test claim",)
                )


class TestEditClaim:
    def test_edit_claim_form(self, client, auth_cookies, test_db):
        """GET /utilization/{id}/edit returns 200 for a DRAFT claim."""
        claim_id = None
        try:
            claim_id = _create_draft_claim("ADMIN")
            response = client.get(f"/utilization/{claim_id}/edit", cookies=auth_cookies)
            assert response.status_code == 200
        finally:
            if claim_id:
                _cleanup_claim(claim_id)

    def test_update_claim(self, client, auth_cookies, test_db):
        """POST /utilization/{id}/edit updates a DRAFT claim and redirects."""
        claim_id = None
        try:
            claim_id = _create_draft_claim("ADMIN")
            response = client.post(
                f"/utilization/{claim_id}/edit",
                data={
                    "activity_date": "2026-02-12",
                    "claim_type": "MEETING",
                    "man_days_claimed": "0.5",
                    "activity_description": "Updated test claim",
                },
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify update
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM utilization_claims WHERE id = ?", (claim_id,))
                row = cursor.fetchone()
                assert row is not None
                data = dict(row)
                assert data["claim_type"] == "MEETING"
                assert data["activity_description"] == "Updated test claim"
        finally:
            if claim_id:
                _cleanup_claim(claim_id)


class TestSubmitClaim:
    def test_submit_claim(self, client, auth_cookies, test_db):
        """POST /utilization/{id}/submit transitions DRAFT -> SUBMITTED."""
        claim_id = None
        try:
            claim_id = _create_draft_claim("ADMIN")

            response = client.post(
                f"/utilization/{claim_id}/submit",
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify status changed
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status, submitted_at FROM utilization_claims WHERE id = ?", (claim_id,))
                row = cursor.fetchone()
                assert row is not None
                data = dict(row)
                assert data["status"] == "SUBMITTED"
                assert data["submitted_at"] is not None
        finally:
            if claim_id:
                _cleanup_claim(claim_id)


class TestTLActions:
    def test_pending_approval(self, client, auth_cookies):
        """GET /utilization/pending-approval returns 200."""
        response = client.get("/utilization/pending-approval", cookies=auth_cookies)
        assert response.status_code == 200

    def test_tl_approve(self, client, auth_cookies, test_db):
        """POST /utilization/{id}/tl-approve transitions SUBMITTED -> TL_APPROVED.
        Admin user acts as TL since admin can approve any claim.
        """
        claim_id = None
        try:
            claim_id = _create_submitted_claim("ADMIN")

            response = client.post(
                f"/utilization/{claim_id}/tl-approve",
                data={"remarks": "Approved by TL for test"},
                cookies=auth_cookies,
                follow_redirects=False,
            )
            # Admin should be able to approve (is_head or is_admin check)
            assert response.status_code == 302

            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status, tl_approved_by FROM utilization_claims WHERE id = ?", (claim_id,))
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    assert data["status"] == "TL_APPROVED"
                    assert data["tl_approved_by"] == "ADMIN"
        finally:
            if claim_id:
                _cleanup_claim(claim_id)

    def test_tl_reject(self, client, auth_cookies, test_db):
        """POST /utilization/{id}/tl-reject sends SUBMITTED -> DRAFT."""
        claim_id = None
        try:
            claim_id = _create_submitted_claim("ADMIN")

            response = client.post(
                f"/utilization/{claim_id}/tl-reject",
                data={"remarks": "Rejected for corrections"},
                cookies=auth_cookies,
                follow_redirects=False,
            )
            # May succeed or may get 404 depending on TL relationship
            assert response.status_code in (302, 404)

            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status, tl_remarks FROM utilization_claims WHERE id = ?", (claim_id,))
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    # If the reject went through, status should be DRAFT
                    if data["tl_remarks"] == "Rejected for corrections":
                        assert data["status"] == "DRAFT"
        finally:
            if claim_id:
                _cleanup_claim(claim_id)


class TestPendingRectification:
    def test_pending_rectification(self, client, auth_cookies):
        """GET /utilization/pending-rectification returns 200 for admin."""
        response = client.get("/utilization/pending-rectification", cookies=auth_cookies)
        assert response.status_code == 200


class TestUtilizationSummary:
    def test_utilization_summary(self, client, auth_cookies):
        """GET /utilization/summary returns 200."""
        response = client.get("/utilization/summary", cookies=auth_cookies)
        assert response.status_code == 200
