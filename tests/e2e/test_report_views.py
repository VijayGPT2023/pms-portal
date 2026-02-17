"""
E2E tests for Report pages: Delay Dashboard, Physical Progress, Financial Progress,
and the Dashboard Summary API.
"""
import os
import sys
import pytest
import requests
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestDelayDashboard:
    """Test the delay dashboard end-to-end: navigation, 4 delay categories, filtering."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def _seed_delay_data(self):
        """Insert test data to ensure delay categories have entries."""
        from app.database import get_db
        ids = {"assignments": [], "milestones": [], "invoices": []}
        past_date = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        far_past = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")

        with get_db() as conn:
            cursor = conn.cursor()

            # Create an assignment stuck in REGISTRATION for >30 days (activation delay)
            cursor.execute("""
                INSERT INTO assignments (assignment_no, title, type, office_id, status,
                    workflow_stage, registration_status, created_at, registered_by)
                VALUES ('DLY-E2E-001', 'E2E Delay Activation Test', 'ASSIGNMENT',
                        (SELECT office_id FROM offices LIMIT 1),
                        'Not Started', 'REGISTRATION', 'PENDING_APPROVAL', ?, 'ADMIN')
            """, (far_past,))
            cursor.execute("SELECT id FROM assignments WHERE assignment_no = 'DLY-E2E-001'")
            asgn_row = cursor.fetchone()
            if asgn_row:
                ids["assignments"].append(asgn_row["id"])

            # Create an active assignment with past-due milestones (milestone delay + invoice delay)
            cursor.execute("""
                INSERT INTO assignments (assignment_no, title, type, office_id, status,
                    workflow_stage, registration_status, total_value, registered_by)
                VALUES ('DLY-E2E-002', 'E2E Delay Milestone Test', 'ASSIGNMENT',
                        (SELECT office_id FROM offices LIMIT 1),
                        'Ongoing', 'ACTIVE', 'APPROVED', 1000000, 'ADMIN')
            """)
            cursor.execute("SELECT id FROM assignments WHERE assignment_no = 'DLY-E2E-002'")
            asgn_row = cursor.fetchone()
            if asgn_row:
                aid = asgn_row["id"]
                ids["assignments"].append(aid)

                # Milestone with past target_date, not completed, no invoice
                cursor.execute("""
                    INSERT INTO milestones (assignment_id, milestone_no, title, target_date,
                        status, invoice_raised, invoice_percent)
                    VALUES (?, 1, 'E2E Delay Milestone 1', ?, 'Not Started', 0, 50)
                """, (aid, past_date))
                cursor.execute(
                    "SELECT id FROM milestones WHERE assignment_id = ? AND title = 'E2E Delay Milestone 1'",
                    (aid,),
                )
                m_row = cursor.fetchone()
                if m_row:
                    ids["milestones"].append(m_row["id"])

            # Create an approved invoice without payment (payment delay)
            cursor.execute("""
                INSERT INTO assignments (assignment_no, title, type, office_id, status,
                    workflow_stage, registration_status, total_value, registered_by)
                VALUES ('DLY-E2E-003', 'E2E Delay Payment Test', 'ASSIGNMENT',
                        (SELECT office_id FROM offices LIMIT 1),
                        'Ongoing', 'ACTIVE', 'APPROVED', 500000, 'ADMIN')
            """)
            cursor.execute("SELECT id FROM assignments WHERE assignment_no = 'DLY-E2E-003'")
            asgn_row = cursor.fetchone()
            if asgn_row:
                aid3 = asgn_row["id"]
                ids["assignments"].append(aid3)

                cursor.execute("""
                    INSERT INTO invoice_requests (request_number, assignment_id, invoice_type,
                        invoice_amount, status, requested_by, approved_at, fy_period)
                    VALUES ('INV-E2E-DLY-001', ?, 'ADVANCE', 250000, 'APPROVED',
                            'ADMIN', ?, '2025-26')
                """, (aid3, far_past))
                cursor.execute(
                    "SELECT id FROM invoice_requests WHERE request_number = 'INV-E2E-DLY-001'"
                )
                inv_row = cursor.fetchone()
                if inv_row:
                    ids["invoices"].append(inv_row["id"])

        return ids

    def _cleanup_delay_data(self, ids):
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            for inv_id in ids.get("invoices", []):
                cursor.execute("DELETE FROM payment_receipts WHERE invoice_request_id = ?", (inv_id,))
                cursor.execute("DELETE FROM officer_revenue_ledger WHERE invoice_request_id = ?", (inv_id,))
                cursor.execute("DELETE FROM invoice_milestone_links WHERE invoice_request_id = ?", (inv_id,))
                cursor.execute("DELETE FROM invoice_requests WHERE id = ?", (inv_id,))
            for m_id in ids.get("milestones", []):
                cursor.execute("DELETE FROM milestones WHERE id = ?", (m_id,))
            for a_id in ids.get("assignments", []):
                cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (a_id,))
                cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (a_id,))
                cursor.execute("DELETE FROM assignments WHERE id = ?", (a_id,))

    def test_delay_dashboard_end_to_end(self, base_url):
        """Login -> Navigate to delay dashboard -> Verify 4 categories -> Filter by office."""
        session = self._login(base_url)
        ids = self._seed_delay_data()

        try:
            # Step 1: Navigate to delay dashboard
            response = session.get(f"{base_url}/reports/delays")
            assert response.status_code == 200

            # Step 2: Verify the page contains the 4 delay category sections
            text = response.text.lower()
            assert "payment" in text  # payment delays section
            assert "invoice" in text  # invoice delays section
            assert "milestone" in text  # milestone delays section
            assert "activation" in text or "workflow" in text  # activation delays section

            # Step 3: Verify the seeded data appears
            assert "DLY-E2E" in response.text or "E2E Delay" in response.text

            # Step 4: Filter by office
            from app.database import get_db
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT office_id FROM offices LIMIT 1")
                office_row = cursor.fetchone()

            if office_row:
                office_id = office_row["office_id"]
                response = session.get(f"{base_url}/reports/delays?office={office_id}")
                assert response.status_code == 200

            # Step 5: Test the delay summary API
            response = session.get(f"{base_url}/reports/delays/api/summary")
            assert response.status_code == 200
            data = response.json()
            assert "payment_delays" in data
            assert "invoice_delays" in data
            assert "milestone_delays" in data
            assert "activation_delays" in data
            assert "total" in data

        finally:
            self._cleanup_delay_data(ids)


class TestPhysicalProgressViews:
    """Test physical progress report views: office, domain, officer views."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_physical_progress_views(self, base_url):
        """View physical progress by office -> domain -> officer -> verify data."""
        session = self._login(base_url)

        # Step 1: View physical progress by office (default view)
        response = session.get(f"{base_url}/reports/physical-progress")
        assert response.status_code == 200
        text = response.text.lower()
        assert "progress" in text or "physical" in text

        # Step 2: Switch to domain view
        response = session.get(f"{base_url}/reports/physical-progress?view=domain")
        assert response.status_code == 200

        # Step 3: Switch to officer view
        response = session.get(f"{base_url}/reports/physical-progress?view=officer")
        assert response.status_code == 200

        # Step 4: Switch to type view
        response = session.get(f"{base_url}/reports/physical-progress?view=type")
        assert response.status_code == 200

        # Step 5: Test the physical progress API
        response = session.get(f"{base_url}/reports/physical-progress/api/data")
        assert response.status_code == 200
        data = response.json()
        assert "by_status" in data
        assert isinstance(data["by_status"], list)

        # Step 6: Filter by type
        response = session.get(
            f"{base_url}/reports/physical-progress?view=office&type=ASSIGNMENT"
        )
        assert response.status_code == 200


class TestFinancialProgressViews:
    """Test financial progress report views."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_financial_progress_views(self, base_url):
        """View financial progress -> Check all view tabs -> Verify expenditure breakdown."""
        session = self._login(base_url)

        # Step 1: View financial progress by office (default)
        response = session.get(f"{base_url}/reports/financial-progress")
        assert response.status_code == 200
        text = response.text.lower()
        assert "financial" in text or "progress" in text or "revenue" in text

        # Step 2: Switch to domain view
        response = session.get(f"{base_url}/reports/financial-progress?view=domain")
        assert response.status_code == 200

        # Step 3: Switch to type view
        response = session.get(f"{base_url}/reports/financial-progress?view=type")
        assert response.status_code == 200

        # Step 4: Test financial progress API
        response = session.get(f"{base_url}/reports/financial-progress/api/data")
        assert response.status_code == 200
        data = response.json()
        assert "total_value" in data
        assert "invoiced" in data
        assert "received" in data
        assert "expenditure" in data
        assert "net" in data

        # Step 5: Test with office filter
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT office_id FROM offices LIMIT 1")
            office_row = cursor.fetchone()

        if office_row:
            response = session.get(
                f"{base_url}/reports/financial-progress/api/data?office={office_row['office_id']}"
            )
            assert response.status_code == 200
            data = response.json()
            assert "total_value" in data


class TestDashboardSummaryAPI:
    """Test the dashboard summary API that combines delays, physical, and financial data."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_dashboard_summary_api_integration(self, base_url):
        """Call summary API -> Verify JSON structure has delays, physical, financial keys."""
        session = self._login(base_url)

        # Step 1: Call the dashboard summary API
        response = session.get(f"{base_url}/reports/api/dashboard-summary")
        assert response.status_code == 200

        data = response.json()

        # Step 2: Verify top-level keys exist
        assert "delays" in data
        assert "physical_progress" in data
        assert "financial" in data

        # Step 3: Verify delays structure
        delays = data["delays"]
        assert "payment" in delays
        assert "invoice" in delays
        assert "milestone" in delays
        assert "activation" in delays

        # Step 4: Verify physical_progress structure
        phys = data["physical_progress"]
        assert "avg_percent" in phys
        assert "on_track" in phys
        assert "delayed" in phys
        assert "completed" in phys

        # Step 5: Verify financial structure
        fin = data["financial"]
        assert "total_value" in fin
        assert "invoiced" in fin
        assert "received" in fin
        assert "expenditure" in fin
        assert "net" in fin
        assert "surplus_deficit" in fin

        # Step 6: Test with office filter
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT office_id FROM offices LIMIT 1")
            office_row = cursor.fetchone()

        if office_row:
            response = session.get(
                f"{base_url}/reports/api/dashboard-summary?office={office_row['office_id']}"
            )
            assert response.status_code == 200
            data = response.json()
            assert "delays" in data
            assert "physical_progress" in data
            assert "financial" in data

        # Step 7: Unauthenticated access should return 401
        unauth = requests.Session()
        response = unauth.get(f"{base_url}/reports/api/dashboard-summary")
        assert response.status_code == 401
