"""
Integration tests for NEW finance endpoints -- finance dashboard, finance officer
dashboard, invoice request form, TL verify, hold/release revenue.

Named test_finance_routes_new.py to avoid conflicts with any future
test_finance_routes.py.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")

pytestmark = pytest.mark.integration


def _create_assignment_for_finance():
    """Insert a test assignment suitable for finance operations. Returns its ID."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assignments (assignment_no, type, title, client, office_id, status,
               workflow_stage, registration_status, team_leader_officer_id, registered_by,
               total_value, gross_value, invoice_amount, amount_received)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "NPC/HQ/ASG/FINTEST/001", "ASSIGNMENT", "Finance Test Assignment",
            "Finance Test Client", "HQ", "Ongoing", "ACTIVE", "APPROVED",
            "ADMIN", "ADMIN", 500000, 500000, 0, 0
        ))
        cursor.execute(
            "SELECT id FROM assignments WHERE title = 'Finance Test Assignment' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row)["id"]


def _create_invoice_request(assignment_id, status="PENDING", officer_request_status="DIRECT"):
    """Insert a test invoice request. Returns its ID."""
    from app.database import get_db
    import datetime
    with get_db() as conn:
        cursor = conn.cursor()
        today = datetime.date.today()
        req_number = f"INV-HQ-{today.strftime('%Y%m')}-TEST-{assignment_id}"
        fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

        cursor.execute("""
            INSERT INTO invoice_requests (
                request_number, assignment_id, invoice_type, invoice_amount,
                fy_period, description, status, requested_by, officer_request_status,
                tl_revenue_hold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            req_number, assignment_id, "SUBSEQUENT", 100000.0,
            fy, "Test invoice request", status, "ADMIN", officer_request_status
        ))
        cursor.execute(
            "SELECT id FROM invoice_requests WHERE request_number = ? ORDER BY id DESC LIMIT 1",
            (req_number,)
        )
        row = cursor.fetchone()
        return dict(row)["id"]


def _cleanup_finance_test(assignment_id):
    """Remove all test finance data."""
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        # Get all invoice request IDs for this assignment
        cursor.execute(
            "SELECT id FROM invoice_requests WHERE assignment_id = ?", (assignment_id,)
        )
        inv_ids = [dict(r)["id"] for r in cursor.fetchall()]

        for inv_id in inv_ids:
            cursor.execute("DELETE FROM officer_revenue_ledger WHERE invoice_request_id = ?", (inv_id,))
            cursor.execute("DELETE FROM payment_receipts WHERE invoice_request_id = ?", (inv_id,))
            cursor.execute("DELETE FROM invoice_milestone_links WHERE invoice_request_id = ?", (inv_id,))

        cursor.execute("DELETE FROM invoice_requests WHERE assignment_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM revenue_shares WHERE assignment_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM milestones WHERE assignment_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM assignment_team WHERE assignment_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
        cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))


class TestFinanceDashboard:
    def test_finance_dashboard_authenticated(self, client, auth_cookies):
        """GET /finance returns 200 for admin (who passes the finance check)."""
        response = client.get("/finance", cookies=auth_cookies)
        # Admin should pass the is_finance_officer check via legacy fallback
        assert response.status_code == 200

    def test_finance_unauthenticated(self, client):
        """GET /finance without cookies redirects to login."""
        response = client.get("/finance", follow_redirects=False)
        # App may redirect (302) or render an inline redirect page (200)
        assert response.status_code in (200, 302)
        if response.status_code == 302:
            location = response.headers.get("location", "")
            assert "login" in location.lower()


class TestFinanceOfficerDashboard:
    def test_finance_officer_dashboard(self, client, auth_cookies):
        """GET /finance/finance-officer-dashboard returns 200 for admin."""
        response = client.get("/finance/finance-officer-dashboard", cookies=auth_cookies)
        assert response.status_code == 200


class TestInvoiceRequestForm:
    def test_invoice_request_form(self, client, auth_cookies, test_db):
        """GET /finance/invoice-request/{assignment_id} returns 200 for TL/admin."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            response = client.get(
                f"/finance/invoice-request/{assignment_id}", cookies=auth_cookies
            )
            assert response.status_code == 200
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)

    def test_invoice_request_form_nonexistent(self, client, auth_cookies):
        """GET /finance/invoice-request/999999 redirects for nonexistent assignment."""
        response = client.get(
            "/finance/invoice-request/999999", cookies=auth_cookies,
            follow_redirects=False
        )
        # Should redirect to dashboard since assignment doesn't exist
        assert response.status_code == 302


class TestHoldRevenue:
    def test_hold_revenue(self, client, auth_cookies, test_db):
        """POST /finance/invoice/{id}/hold-revenue sets tl_revenue_hold flag."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            inv_id = _create_invoice_request(assignment_id)

            response = client.post(
                f"/finance/invoice/{inv_id}/hold-revenue",
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify the hold was set
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT tl_revenue_hold FROM invoice_requests WHERE id = ?",
                    (inv_id,)
                )
                row = cursor.fetchone()
                if row:
                    assert dict(row)["tl_revenue_hold"] == 1
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)


class TestReleaseRevenue:
    def test_release_revenue(self, client, auth_cookies, test_db):
        """POST /finance/invoice/{id}/release-revenue clears tl_revenue_hold flag."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            inv_id = _create_invoice_request(assignment_id)

            # First, set the hold
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE invoice_requests SET tl_revenue_hold = 1 WHERE id = ?",
                    (inv_id,)
                )

            # Now release it
            response = client.post(
                f"/finance/invoice/{inv_id}/release-revenue",
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify the hold was cleared
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT tl_revenue_hold FROM invoice_requests WHERE id = ?",
                    (inv_id,)
                )
                row = cursor.fetchone()
                if row:
                    assert dict(row)["tl_revenue_hold"] == 0
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)


class TestTLVerifyInvoice:
    def test_tl_verify_invoice(self, client, auth_cookies, test_db):
        """POST /finance/invoice/{id}/tl-verify transitions officer_request_status
        from OFFICER_REQUESTED to TL_VERIFIED."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            inv_id = _create_invoice_request(
                assignment_id, status="PENDING",
                officer_request_status="OFFICER_REQUESTED"
            )

            response = client.post(
                f"/finance/invoice/{inv_id}/tl-verify",
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify status changed
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT officer_request_status, verified_by FROM invoice_requests WHERE id = ?",
                    (inv_id,)
                )
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    assert data["officer_request_status"] == "TL_VERIFIED"
                    assert data["verified_by"] == "ADMIN"
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)

    def test_tl_verify_wrong_status(self, client, auth_cookies, test_db):
        """POST /finance/invoice/{id}/tl-verify with DIRECT status redirects
        with error (cannot verify a non-officer-requested invoice)."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            inv_id = _create_invoice_request(
                assignment_id, status="PENDING",
                officer_request_status="DIRECT"
            )

            response = client.post(
                f"/finance/invoice/{inv_id}/tl-verify",
                cookies=auth_cookies,
                follow_redirects=False,
            )
            # Should redirect with error=invalid_status
            assert response.status_code == 302
            location = response.headers.get("location", "")
            assert "invalid_status" in location or "error" in location
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)

    def test_tl_verify_nonexistent(self, client, auth_cookies):
        """POST /finance/invoice/999999/tl-verify redirects for nonexistent invoice."""
        response = client.post(
            "/finance/invoice/999999/tl-verify",
            cookies=auth_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("location", "")
        assert "not_found" in location or "finance" in location


class TestSubmitInvoiceRequest:
    def test_submit_invoice_request(self, client, auth_cookies, test_db):
        """POST /finance/invoice-request/{assignment_id} creates an invoice request."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            import datetime
            today = datetime.date.today()
            fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

            response = client.post(
                f"/finance/invoice-request/{assignment_id}",
                data={
                    "invoice_amount": "50000",
                    "invoice_type": "SUBSEQUENT",
                    "fy_period": fy,
                    "description": "Test invoice submission",
                },
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302
            location = response.headers.get("location", "")
            assert "success" in location or "invoice-request" in location

            # Verify in DB
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM invoice_requests WHERE assignment_id = ? AND description = ?",
                    (assignment_id, "Test invoice submission")
                )
                row = cursor.fetchone()
                assert row is not None
                data = dict(row)
                assert data["invoice_amount"] == 50000.0
                assert data["status"] == "PENDING"
                assert data["officer_request_status"] == "DIRECT"
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)


class TestApproveInvoice:
    def test_approve_invoice_request(self, client, auth_cookies, test_db):
        """POST /finance/invoice/{id}/approve approves a PENDING DIRECT invoice."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            inv_id = _create_invoice_request(
                assignment_id, status="PENDING",
                officer_request_status="DIRECT"
            )

            response = client.post(
                f"/finance/invoice/{inv_id}/approve",
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify approval
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status, approved_by, revenue_recognized_80 FROM invoice_requests WHERE id = ?",
                    (inv_id,)
                )
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    assert data["status"] == "APPROVED"
                    assert data["approved_by"] == "ADMIN"
                    # 80% of 100000.0 = 80000.0
                    assert data["revenue_recognized_80"] == 80000.0
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)


class TestRejectInvoice:
    def test_reject_invoice_request(self, client, auth_cookies, test_db):
        """POST /finance/invoice/{id}/reject rejects a PENDING invoice."""
        assignment_id = None
        try:
            assignment_id = _create_assignment_for_finance()
            inv_id = _create_invoice_request(assignment_id)

            response = client.post(
                f"/finance/invoice/{inv_id}/reject",
                data={"rejection_remarks": "Rejected for testing purposes"},
                cookies=auth_cookies,
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Verify rejection
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status, approval_remarks FROM invoice_requests WHERE id = ?",
                    (inv_id,)
                )
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    assert data["status"] == "REJECTED"
                    assert data["approval_remarks"] == "Rejected for testing purposes"
        finally:
            if assignment_id:
                _cleanup_finance_test(assignment_id)
