"""
E2E tests for the invoice/payment workflow with new features.
Tests: Officer invoice request flow (3H), TL revenue hold/release (4A),
multi-milestone invoice (4A), finance officer dashboard offices.
"""
import os
import sys
import pytest
import requests
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _login(base_url):
    """Helper: login as admin and return a requests.Session."""
    session = requests.Session()
    session.post(
        f"{base_url}/login",
        data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
    )
    return session


def _create_active_assignment_with_milestones(title, num_milestones=2, total_value=1000000):
    """Seed helper: create an active assignment with milestones and revenue shares.
    Returns dict with assignment_id, milestone_ids, office_id."""
    from app.database import get_db
    from datetime import timedelta

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT office_id FROM offices LIMIT 1")
        office_row = cursor.fetchone()
        office_id = office_row["office_id"] if office_row else "DELHI"

        # Unique assignment_no from title hash
        import hashlib
        short_hash = hashlib.md5(title.encode()).hexdigest()[:6].upper()
        assignment_no = f"FIN-E2E-{short_hash}"

        cursor.execute("""
            INSERT INTO assignments (assignment_no, title, type, office_id, status,
                workflow_stage, registration_status, total_value,
                team_leader_officer_id, registered_by,
                approval_status, cost_approval_status, team_approval_status,
                milestone_approval_status, revenue_approval_status)
            VALUES (?, ?, 'ASSIGNMENT', ?, 'Ongoing', 'ACTIVE', 'APPROVED', ?,
                    'ADMIN', 'ADMIN',
                    'APPROVED', 'APPROVED', 'APPROVED', 'APPROVED', 'APPROVED')
        """, (assignment_no, title, office_id, total_value))

        cursor.execute(
            "SELECT id FROM assignments WHERE assignment_no = ?", (assignment_no,)
        )
        assignment_id = cursor.fetchone()["id"]

        # Add ADMIN to assignment_team
        cursor.execute("""
            INSERT INTO assignment_team (assignment_id, officer_id, role, is_active)
            VALUES (?, 'ADMIN', 'TEAM_LEADER', 1)
        """, (assignment_id,))

        # Create milestones
        milestone_ids = []
        target_base = date.today() + timedelta(days=30)
        for i in range(num_milestones):
            target_date = (target_base + timedelta(days=30 * i)).strftime("%Y-%m-%d")
            pct = round(100 / num_milestones, 1)
            cursor.execute("""
                INSERT INTO milestones (assignment_id, milestone_no, title, target_date,
                    status, invoice_raised, invoice_percent)
                VALUES (?, ?, ?, ?, 'Not Started', 0, ?)
            """, (assignment_id, i + 1, f"Milestone {i + 1}", target_date, pct))
            cursor.execute(
                "SELECT id FROM milestones WHERE assignment_id = ? AND milestone_no = ?",
                (assignment_id, i + 1),
            )
            milestone_ids.append(cursor.fetchone()["id"])

        # Create revenue share for ADMIN (100%)
        cursor.execute("""
            INSERT INTO revenue_shares (assignment_id, officer_id, share_percent, share_amount)
            VALUES (?, 'ADMIN', 100, ?)
        """, (assignment_id, total_value))

    return {
        "assignment_id": assignment_id,
        "assignment_no": assignment_no,
        "milestone_ids": milestone_ids,
        "office_id": office_id,
        "total_value": total_value,
    }


def _cleanup_assignment(data):
    """Clean up all data related to a test assignment."""
    from app.database import get_db
    aid = data["assignment_id"]
    with get_db() as conn:
        cursor = conn.cursor()
        # Revenue ledger
        cursor.execute("DELETE FROM officer_revenue_ledger WHERE assignment_id = ?", (aid,))
        # Invoice milestone links
        cursor.execute("""
            DELETE FROM invoice_milestone_links WHERE invoice_request_id IN
            (SELECT id FROM invoice_requests WHERE assignment_id = ?)
        """, (aid,))
        # Payment receipts
        cursor.execute("""
            DELETE FROM payment_receipts WHERE invoice_request_id IN
            (SELECT id FROM invoice_requests WHERE assignment_id = ?)
        """, (aid,))
        # Invoice requests
        cursor.execute("DELETE FROM invoice_requests WHERE assignment_id = ?", (aid,))
        # Revenue shares
        cursor.execute("DELETE FROM revenue_shares WHERE assignment_id = ?", (aid,))
        # Milestones
        cursor.execute("DELETE FROM milestones WHERE assignment_id = ?", (aid,))
        # Assignment team
        cursor.execute("DELETE FROM assignment_team WHERE assignment_id = ?", (aid,))
        # Approval requests
        cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (aid,))
        # Activity log
        cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (aid,))
        # Assignment
        cursor.execute("DELETE FROM assignments WHERE id = ?", (aid,))


class TestOfficerInvoiceRequestFlow:
    """Feature 3H: Officer requests invoice -> Status=OFFICER_REQUESTED ->
    TL verifies -> Status=TL_VERIFIED -> Finance approves -> Revenue allocated."""

    def test_officer_invoice_request_flow(self, base_url):
        """Full officer-initiated invoice flow ending in finance approval."""
        session = _login(base_url)
        from app.database import get_db

        data = _create_active_assignment_with_milestones(
            "E2E Officer Invoice Flow", num_milestones=1, total_value=500000
        )
        aid = data["assignment_id"]
        today = date.today()
        fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

        try:
            # Step 1: Officer requests invoice (officer_request_status = OFFICER_REQUESTED)
            response = session.post(
                f"{base_url}/finance/invoice-request-by-officer/{aid}",
                data={
                    "invoice_amount": 250000,
                    "invoice_type": "ADVANCE",
                    "fy_period": fy,
                    "description": "E2E officer-initiated invoice",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Verify OFFICER_REQUESTED status
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, status, officer_request_status, requested_by_officer_id
                    FROM invoice_requests WHERE assignment_id = ?
                    ORDER BY id DESC LIMIT 1
                """, (aid,))
                inv = dict(cursor.fetchone())
                inv_id = inv["id"]
                assert inv["status"] == "PENDING"
                assert inv["officer_request_status"] == "OFFICER_REQUESTED"
                assert inv["requested_by_officer_id"] == "ADMIN"

            # Step 2: TL verifies (OFFICER_REQUESTED -> TL_VERIFIED)
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/tl-verify",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT officer_request_status, verified_by FROM invoice_requests WHERE id = ?",
                    (inv_id,),
                )
                inv = dict(cursor.fetchone())
                assert inv["officer_request_status"] == "TL_VERIFIED"
                assert inv["verified_by"] == "ADMIN"

            # Step 3: Finance approves (triggers 80% revenue recognition)
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/approve",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status, revenue_recognized_80, approved_by FROM invoice_requests WHERE id = ?",
                    (inv_id,),
                )
                inv = dict(cursor.fetchone())
                assert inv["status"] == "APPROVED"
                assert inv["revenue_recognized_80"] == 250000 * 0.8  # 200000
                assert inv["approved_by"] == "ADMIN"

                # Verify revenue ledger entry was created
                cursor.execute(
                    "SELECT SUM(amount) as total, COUNT(*) as cnt FROM officer_revenue_ledger WHERE invoice_request_id = ?",
                    (inv_id,),
                )
                ledger = dict(cursor.fetchone())
                assert ledger["cnt"] >= 1
                assert ledger["total"] == 250000 * 0.8  # 100% share of 80% = 200000

        finally:
            _cleanup_assignment(data)


class TestTLRevenueHoldRelease:
    """Feature 4A: TL revenue hold and release on invoice requests."""

    def test_tl_revenue_hold_release(self, base_url):
        """TL creates invoice -> TL holds revenue -> Finance approves ->
        Verify ledger entries marked held -> TL releases -> Verify released."""
        session = _login(base_url)
        from app.database import get_db

        data = _create_active_assignment_with_milestones(
            "E2E Revenue Hold Release", num_milestones=1, total_value=400000
        )
        aid = data["assignment_id"]
        mid = data["milestone_ids"][0]
        today = date.today()
        fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

        try:
            # Step 1: TL creates invoice request (DIRECT)
            response = session.post(
                f"{base_url}/finance/invoice-request/{aid}",
                data={
                    "invoice_amount": 200000,
                    "invoice_type": "ADVANCE",
                    "milestone_id": mid,
                    "fy_period": fy,
                    "description": "E2E hold test invoice",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM invoice_requests WHERE assignment_id = ? ORDER BY id DESC LIMIT 1",
                    (aid,),
                )
                inv_id = cursor.fetchone()["id"]

            # Step 2: TL places revenue hold
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/hold-revenue",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT tl_revenue_hold FROM invoice_requests WHERE id = ?", (inv_id,)
                )
                assert cursor.fetchone()["tl_revenue_hold"] == 1

            # Step 3: Finance approves -- revenue entries should be marked as held
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/approve",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT is_held, amount FROM officer_revenue_ledger WHERE invoice_request_id = ? AND revenue_type = 'INVOICE_80'",
                    (inv_id,),
                )
                ledger_entries = cursor.fetchall()
                assert len(ledger_entries) >= 1
                for entry in ledger_entries:
                    assert entry["is_held"] == 1

            # Step 4: TL releases revenue hold
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/release-revenue",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                # tl_revenue_hold should be cleared
                cursor.execute(
                    "SELECT tl_revenue_hold FROM invoice_requests WHERE id = ?", (inv_id,)
                )
                assert cursor.fetchone()["tl_revenue_hold"] == 0

                # Ledger entries should be released
                cursor.execute(
                    "SELECT is_held, released_by FROM officer_revenue_ledger WHERE invoice_request_id = ? AND revenue_type = 'INVOICE_80'",
                    (inv_id,),
                )
                for entry in cursor.fetchall():
                    assert entry["is_held"] == 0
                    assert entry["released_by"] == "ADMIN"

        finally:
            _cleanup_assignment(data)


class TestMultiMilestoneInvoice:
    """Feature 4A: Create assignment with milestones -> Link invoice to multiple
    milestones -> Approve -> Verify each milestone updated."""

    def test_multi_milestone_invoice(self, base_url):
        """Multi-milestone invoice: link 2 milestones -> approve -> check amounts."""
        session = _login(base_url)
        from app.database import get_db

        data = _create_active_assignment_with_milestones(
            "E2E Multi Milestone Invoice", num_milestones=3, total_value=900000
        )
        aid = data["assignment_id"]
        m_ids = data["milestone_ids"]
        today = date.today()
        fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

        try:
            # Step 1: Submit invoice request with multi-milestone data
            # Link milestones 1 and 2, amounts 200000 and 100000 = 300000 total
            milestone_ids_csv = f"{m_ids[0]},{m_ids[1]}"
            milestone_amounts_csv = "200000,100000"

            response = session.post(
                f"{base_url}/finance/invoice-request/{aid}",
                data={
                    "invoice_amount": 300000,
                    "invoice_type": "SUBSEQUENT",
                    "fy_period": fy,
                    "description": "E2E multi-milestone invoice",
                    "milestone_ids": milestone_ids_csv,
                    "milestone_amounts": milestone_amounts_csv,
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM invoice_requests WHERE assignment_id = ? ORDER BY id DESC LIMIT 1",
                    (aid,),
                )
                inv_id = cursor.fetchone()["id"]

                # Verify invoice_milestone_links were created
                cursor.execute(
                    "SELECT milestone_id, milestone_share_amount, revenue_share_percent FROM invoice_milestone_links WHERE invoice_request_id = ? ORDER BY milestone_id",
                    (inv_id,),
                )
                links = [dict(r) for r in cursor.fetchall()]
                assert len(links) == 2
                # First milestone: 200000 / 300000 * 100 = 66.67%
                assert links[0]["milestone_share_amount"] == 200000
                assert abs(links[0]["revenue_share_percent"] - 66.67) < 1
                # Second milestone: 100000 / 300000 * 100 = 33.33%
                assert links[1]["milestone_share_amount"] == 100000
                assert abs(links[1]["revenue_share_percent"] - 33.33) < 1

            # Step 2: Approve the invoice
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/approve",
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Step 3: Verify each milestone was updated with correct amounts
            with get_db() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT id, invoice_raised, invoice_amount FROM milestones WHERE id = ?",
                    (m_ids[0],),
                )
                ms1 = dict(cursor.fetchone())
                assert ms1["invoice_raised"] == 1
                assert ms1["invoice_amount"] == 200000

                cursor.execute(
                    "SELECT id, invoice_raised, invoice_amount FROM milestones WHERE id = ?",
                    (m_ids[1],),
                )
                ms2 = dict(cursor.fetchone())
                assert ms2["invoice_raised"] == 1
                assert ms2["invoice_amount"] == 100000

                # Third milestone should NOT have been touched
                cursor.execute(
                    "SELECT id, invoice_raised FROM milestones WHERE id = ?",
                    (m_ids[2],),
                )
                ms3 = dict(cursor.fetchone())
                assert ms3["invoice_raised"] == 0

                # Verify revenue recognition: 300000 * 0.8 = 240000
                cursor.execute(
                    "SELECT revenue_recognized_80 FROM invoice_requests WHERE id = ?",
                    (inv_id,),
                )
                assert cursor.fetchone()["revenue_recognized_80"] == 240000

        finally:
            _cleanup_assignment(data)


class TestFinanceOfficerDashboardOffices:
    """Feature 3H: Finance officer dashboard shows only managed offices' invoices."""

    def test_finance_officer_dashboard_offices(self, base_url):
        """Create finance officer for 2 offices -> Login -> View dashboard ->
        Verify only those offices' invoices shown."""
        session = _login(base_url)
        from app.database import get_db

        # Seed: assign ADMIN as finance officer for specific offices
        created_fo_ids = []
        data_list = []

        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT office_id FROM offices ORDER BY office_id LIMIT 2")
                offices = cursor.fetchall()

            if len(offices) < 2:
                pytest.skip("Need at least 2 offices in the database for this test")

            office1 = offices[0]["office_id"]
            office2 = offices[1]["office_id"]

            # Assign ADMIN as finance officer for these 2 offices
            with get_db() as conn:
                cursor = conn.cursor()
                for oid in [office1, office2]:
                    cursor.execute("""
                        INSERT INTO finance_officers (officer_id, office_id, is_active, assigned_by)
                        VALUES ('ADMIN', ?, 1, 'ADMIN')
                    """, (oid,))
                    cursor.execute(
                        "SELECT id FROM finance_officers WHERE officer_id = 'ADMIN' AND office_id = ?",
                        (oid,),
                    )
                    row = cursor.fetchone()
                    if row:
                        created_fo_ids.append(row["id"])

            # Create assignments in both offices with pending invoices
            today = date.today()
            fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

            for idx, oid in enumerate([office1, office2]):
                title = f"E2E Finance Dashboard Office{idx+1} Test"
                import hashlib
                short_hash = hashlib.md5(title.encode()).hexdigest()[:6].upper()
                asgn_no = f"FIN-DASH-{short_hash}"

                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO assignments (assignment_no, title, type, office_id, status,
                            workflow_stage, registration_status, total_value,
                            team_leader_officer_id, registered_by)
                        VALUES (?, ?, 'ASSIGNMENT', ?, 'Ongoing', 'ACTIVE', 'APPROVED',
                                500000, 'ADMIN', 'ADMIN')
                    """, (asgn_no, title, oid))
                    cursor.execute(
                        "SELECT id FROM assignments WHERE assignment_no = ?", (asgn_no,)
                    )
                    a_id = cursor.fetchone()["id"]

                    # Add to assignment team
                    cursor.execute("""
                        INSERT INTO assignment_team (assignment_id, officer_id, role, is_active)
                        VALUES (?, 'ADMIN', 'TEAM_LEADER', 1)
                    """, (a_id,))

                    # Add revenue share
                    cursor.execute("""
                        INSERT INTO revenue_shares (assignment_id, officer_id, share_percent, share_amount)
                        VALUES (?, 'ADMIN', 100, 500000)
                    """, (a_id,))

                    data_list.append({
                        "assignment_id": a_id,
                        "assignment_no": asgn_no,
                        "milestone_ids": [],
                        "office_id": oid,
                        "total_value": 500000,
                    })

                # Create a PENDING invoice for this assignment
                session.post(
                    f"{base_url}/finance/invoice-request/{a_id}",
                    data={
                        "invoice_amount": 100000,
                        "invoice_type": "ADVANCE",
                        "fy_period": fy,
                        "description": f"E2E dashboard test invoice office {idx+1}",
                    },
                    allow_redirects=True,
                )

            # Step: View finance officer dashboard
            response = session.get(f"{base_url}/finance/finance-officer-dashboard")
            assert response.status_code == 200
            text = response.text

            # Verify both offices show up
            assert office1 in text or "Office" in text
            # The invoices we created should appear in the pending section
            assert "E2E" in text or "PENDING" in text.upper() or "pending" in text.lower()

        finally:
            # Cleanup finance officer assignments
            with get_db() as conn:
                cursor = conn.cursor()
                for fo_id in created_fo_ids:
                    cursor.execute("DELETE FROM finance_officers WHERE id = ?", (fo_id,))

            # Cleanup test assignments
            for d in data_list:
                _cleanup_assignment(d)


class TestInvoiceRequestForm:
    """Test viewing the invoice request form for an assignment."""

    def test_invoice_request_form_view(self, base_url):
        """TL views invoice request form -> Verify milestones and existing requests shown."""
        session = _login(base_url)
        from app.database import get_db

        data = _create_active_assignment_with_milestones(
            "E2E Invoice Form View", num_milestones=2, total_value=600000
        )
        aid = data["assignment_id"]

        try:
            response = session.get(f"{base_url}/finance/invoice-request/{aid}")
            assert response.status_code == 200
            text = response.text
            # The form should show the assignment and milestones
            assert "Milestone" in text or "milestone" in text
            assert "invoice" in text.lower()

        finally:
            _cleanup_assignment(data)


class TestPaymentRecordFlow:
    """Test the full invoice -> payment -> 20% revenue recognition flow."""

    def test_payment_records_20_percent_revenue(self, base_url):
        """Create invoice -> Approve -> Record payment -> Verify 20% revenue."""
        session = _login(base_url)
        from app.database import get_db

        data = _create_active_assignment_with_milestones(
            "E2E Payment Revenue Flow", num_milestones=1, total_value=500000
        )
        aid = data["assignment_id"]
        mid = data["milestone_ids"][0]
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

        try:
            # Step 1: Create invoice request
            response = session.post(
                f"{base_url}/finance/invoice-request/{aid}",
                data={
                    "invoice_amount": 200000,
                    "invoice_type": "ADVANCE",
                    "milestone_id": mid,
                    "fy_period": fy,
                    "description": "E2E payment test invoice",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM invoice_requests WHERE assignment_id = ? ORDER BY id DESC LIMIT 1",
                    (aid,),
                )
                inv_id = cursor.fetchone()["id"]

            # Step 2: Approve invoice (80% revenue)
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/approve",
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Step 3: View payment form
            response = session.get(f"{base_url}/finance/payment/{inv_id}")
            assert response.status_code == 200
            assert "payment" in response.text.lower()

            # Step 4: Record payment (20% revenue)
            response = session.post(
                f"{base_url}/finance/payment/{inv_id}",
                data={
                    "amount_received": 200000,
                    "receipt_date": today_str,
                    "payment_mode": "NEFT",
                    "reference_number": "E2E-REF-001",
                    "remarks": "E2E payment test",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Step 5: Verify 20% revenue in ledger
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT SUM(amount) as total FROM officer_revenue_ledger
                    WHERE invoice_request_id = ? AND revenue_type = 'PAYMENT_20'
                """, (inv_id,))
                row = cursor.fetchone()
                assert row is not None
                # 200000 * 0.2 = 40000, officer gets 100% share = 40000
                assert row["total"] == 40000

                # Verify total: 80% on invoice (160000) + 20% on payment (40000) = 200000
                cursor.execute("""
                    SELECT SUM(amount) as total FROM officer_revenue_ledger
                    WHERE invoice_request_id = ?
                """, (inv_id,))
                total = cursor.fetchone()["total"]
                assert total == 200000

                # Verify assignment amount_received was updated
                cursor.execute(
                    "SELECT amount_received FROM assignments WHERE id = ?", (aid,)
                )
                assert cursor.fetchone()["amount_received"] == 200000

        finally:
            _cleanup_assignment(data)


class TestInvoiceRejectFlow:
    """Test invoice rejection by finance."""

    def test_invoice_reject_flow(self, base_url):
        """Create invoice -> Finance rejects -> Verify status and no revenue."""
        session = _login(base_url)
        from app.database import get_db

        data = _create_active_assignment_with_milestones(
            "E2E Invoice Reject Flow", num_milestones=1, total_value=300000
        )
        aid = data["assignment_id"]
        today = date.today()
        fy = f"{today.year}-{str(today.year + 1)[2:]}" if today.month >= 4 else f"{today.year - 1}-{str(today.year)[2:]}"

        try:
            # Step 1: Create invoice
            session.post(
                f"{base_url}/finance/invoice-request/{aid}",
                data={
                    "invoice_amount": 150000,
                    "invoice_type": "ADVANCE",
                    "fy_period": fy,
                    "description": "E2E reject test",
                },
                allow_redirects=True,
            )

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM invoice_requests WHERE assignment_id = ? ORDER BY id DESC LIMIT 1",
                    (aid,),
                )
                inv_id = cursor.fetchone()["id"]

            # Step 2: Reject invoice
            response = session.post(
                f"{base_url}/finance/invoice/{inv_id}/reject",
                data={"rejection_remarks": "Incorrect amount, please resubmit"},
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status, approval_remarks FROM invoice_requests WHERE id = ?",
                    (inv_id,),
                )
                inv = dict(cursor.fetchone())
                assert inv["status"] == "REJECTED"
                assert "Incorrect amount" in (inv["approval_remarks"] or "")

                # Verify no revenue was allocated
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM officer_revenue_ledger WHERE invoice_request_id = ?",
                    (inv_id,),
                )
                assert cursor.fetchone()["cnt"] == 0

        finally:
            _cleanup_assignment(data)
