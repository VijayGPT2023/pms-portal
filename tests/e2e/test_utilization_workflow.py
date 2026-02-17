"""
E2E tests for the full Utilization Claims workflow.
Tests: claim lifecycle, auto-calculation, rejection flow, summary view.
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


class TestUtilizationClaimLifecycle:
    """Full lifecycle: Officer creates claim (DRAFT) -> Submits -> TL approves ->
    Head rectifies -> Head finalizes (FINAL)."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def _create_assignment_for_claims(self, base_url, session):
        """Create an assignment to link claims to."""
        session.post(
            f"{base_url}/assignment/register",
            data={
                "title": "E2E Utilization Assignment",
                "type": "ASSIGNMENT",
                "client": "Utilization Test Client",
            },
            allow_redirects=True,
        )
        from app.database import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM assignments WHERE title = ?",
                ("E2E Utilization Assignment",),
            )
            row = cursor.fetchone()
            if row:
                # Approve and set status so it appears in the dropdown
                cursor.execute(
                    "UPDATE assignments SET status = 'Ongoing', workflow_stage = 'ACTIVE' WHERE id = ?",
                    (row["id"],),
                )
                return row["id"]
        return None

    def test_utilization_claim_lifecycle(self, base_url):
        """DRAFT -> SUBMITTED -> TL_APPROVED -> HEAD_RECTIFIED -> FINAL."""
        session = self._login(base_url)
        from app.database import get_db

        assignment_id = self._create_assignment_for_claims(base_url, session)
        today = date.today().strftime("%Y-%m-%d")
        claim_id = None

        try:
            # Step 1: View the new claim form
            response = session.get(f"{base_url}/utilization/new")
            assert response.status_code == 200

            # Step 2: Create a new claim (starts as DRAFT)
            response = session.post(
                f"{base_url}/utilization/new",
                data={
                    "assignment_id": assignment_id or "",
                    "activity_date": today,
                    "claim_type": "ASSIGNMENT_WORK",
                    "man_days_claimed": 2.0,
                    "activity_description": "E2E lifecycle test claim",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            # Find the claim
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, status FROM utilization_claims WHERE activity_description = ?",
                    ("E2E lifecycle test claim",),
                )
                row = cursor.fetchone()
                assert row is not None
                claim_id = row["id"]
                assert row["status"] == "DRAFT"

            # Step 3: View claims list
            response = session.get(f"{base_url}/utilization/")
            assert response.status_code == 200

            # Step 4: Submit the claim (DRAFT -> SUBMITTED)
            response = session.post(
                f"{base_url}/utilization/{claim_id}/submit",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM utilization_claims WHERE id = ?", (claim_id,))
                assert cursor.fetchone()["status"] == "SUBMITTED"

            # Step 5: TL approves (SUBMITTED -> TL_APPROVED)
            # Admin can act as TL/Head
            response = session.post(
                f"{base_url}/utilization/{claim_id}/tl-approve",
                data={"remarks": "Good work, approved by TL"},
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status, tl_approved_by FROM utilization_claims WHERE id = ?", (claim_id,))
                row = dict(cursor.fetchone())
                assert row["status"] == "TL_APPROVED"
                assert row["tl_approved_by"] == "ADMIN"

            # Step 6: Head rectifies (TL_APPROVED -> HEAD_RECTIFIED)
            response = session.post(
                f"{base_url}/utilization/{claim_id}/head-rectify",
                data={
                    "rectified_days": 1.5,
                    "remarks": "Rectified to 1.5 days by head",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status, rectified_days, head_rectified_by FROM utilization_claims WHERE id = ?",
                    (claim_id,),
                )
                row = dict(cursor.fetchone())
                assert row["status"] == "HEAD_RECTIFIED"
                assert row["rectified_days"] == 1.5

            # Step 7: Finalize (HEAD_RECTIFIED -> FINAL)
            response = session.post(
                f"{base_url}/utilization/{claim_id}/finalize",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM utilization_claims WHERE id = ?", (claim_id,))
                assert cursor.fetchone()["status"] == "FINAL"

        finally:
            # Cleanup
            with get_db() as conn:
                cursor = conn.cursor()
                if claim_id:
                    cursor.execute("DELETE FROM utilization_claims WHERE id = ?", (claim_id,))
                if assignment_id:
                    cursor.execute("DELETE FROM approval_requests WHERE reference_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM activity_log WHERE entity_id = ?", (assignment_id,))
                    cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))


class TestUtilizationAutoCalculation:
    """Test auto-calculation of man-days for special claim types."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_utilization_auto_calculation(self, base_url):
        """PROPOSAL_PREP with 75L -> 3 days; COMMITTEE with 4 members -> 1.0 day."""
        session = self._login(base_url)
        from app.database import get_db

        today = date.today().strftime("%Y-%m-%d")
        claim_ids = []

        try:
            # Test 1: PROPOSAL_PREP with value 75 Lakhs -> should auto-calculate 3 days
            # (per config: up to 100L = 3 man-days)
            response = session.post(
                f"{base_url}/utilization/new",
                data={
                    "activity_date": today,
                    "claim_type": "PROPOSAL_PREP",
                    "proposal_value_lakhs": 75,
                    "man_days_claimed": 0,  # should be overridden by auto-calc
                    "activity_description": "E2E auto-calc PROPOSAL_PREP 75L",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, man_days_claimed FROM utilization_claims WHERE activity_description = ?",
                    ("E2E auto-calc PROPOSAL_PREP 75L",),
                )
                row = cursor.fetchone()
                assert row is not None
                claim_ids.append(row["id"])
                # 75L falls in slab (50, 100] -> 3 days
                assert row["man_days_claimed"] == 3.0

            # Test 2: COMMITTEE with 4 members -> 4 * 0.25 = 1.0 day
            response = session.post(
                f"{base_url}/utilization/new",
                data={
                    "activity_date": today,
                    "claim_type": "COMMITTEE",
                    "num_committee_members": 4,
                    "man_days_claimed": 0,
                    "activity_description": "E2E auto-calc COMMITTEE 4 members",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, man_days_claimed FROM utilization_claims WHERE activity_description = ?",
                    ("E2E auto-calc COMMITTEE 4 members",),
                )
                row = cursor.fetchone()
                assert row is not None
                claim_ids.append(row["id"])
                assert row["man_days_claimed"] == 1.0

        finally:
            with get_db() as conn:
                cursor = conn.cursor()
                for cid in claim_ids:
                    cursor.execute("DELETE FROM utilization_claims WHERE id = ?", (cid,))


class TestUtilizationRejectionFlow:
    """Test rejection flow: Create -> Submit -> TL rejects (back to DRAFT) ->
    Officer edits -> Resubmits."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_utilization_rejection_flow(self, base_url):
        """DRAFT -> SUBMITTED -> TL rejects -> DRAFT -> Edit -> Resubmit."""
        session = self._login(base_url)
        from app.database import get_db

        today = date.today().strftime("%Y-%m-%d")
        claim_id = None

        try:
            # Step 1: Create claim
            response = session.post(
                f"{base_url}/utilization/new",
                data={
                    "activity_date": today,
                    "claim_type": "TRAVEL",
                    "man_days_claimed": 3.0,
                    "activity_description": "E2E rejection flow original",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, status FROM utilization_claims WHERE activity_description = ?",
                    ("E2E rejection flow original",),
                )
                row = cursor.fetchone()
                assert row is not None
                claim_id = row["id"]
                assert row["status"] == "DRAFT"

            # Step 2: Submit
            response = session.post(
                f"{base_url}/utilization/{claim_id}/submit",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM utilization_claims WHERE id = ?", (claim_id,))
                assert cursor.fetchone()["status"] == "SUBMITTED"

            # Step 3: TL rejects (back to DRAFT)
            response = session.post(
                f"{base_url}/utilization/{claim_id}/tl-reject",
                data={"remarks": "Please correct the days, seems too high"},
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status, tl_remarks FROM utilization_claims WHERE id = ?", (claim_id,))
                row = dict(cursor.fetchone())
                assert row["status"] == "DRAFT"
                assert "correct" in (row["tl_remarks"] or "").lower()

            # Step 4: Officer edits the claim (only DRAFT can be edited)
            response = session.post(
                f"{base_url}/utilization/{claim_id}/edit",
                data={
                    "activity_date": today,
                    "claim_type": "TRAVEL",
                    "man_days_claimed": 1.5,
                    "activity_description": "E2E rejection flow corrected",
                },
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT man_days_claimed, activity_description FROM utilization_claims WHERE id = ?",
                    (claim_id,),
                )
                row = dict(cursor.fetchone())
                assert row["man_days_claimed"] == 1.5
                assert "corrected" in row["activity_description"]

            # Step 5: Resubmit
            response = session.post(
                f"{base_url}/utilization/{claim_id}/submit",
                allow_redirects=False,
            )
            assert response.status_code == 302

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM utilization_claims WHERE id = ?", (claim_id,))
                assert cursor.fetchone()["status"] == "SUBMITTED"

        finally:
            with get_db() as conn:
                cursor = conn.cursor()
                if claim_id:
                    cursor.execute("DELETE FROM utilization_claims WHERE id = ?", (claim_id,))


class TestUtilizationSummaryView:
    """Test utilization summary MIS view."""

    def _login(self, base_url):
        session = requests.Session()
        session.post(
            f"{base_url}/login",
            data={"email": "admin@npcindia.gov.in", "password": "e2e_admin_pass"},
        )
        return session

    def test_utilization_summary_view(self, base_url):
        """Create claims -> View summary -> Verify display."""
        session = self._login(base_url)
        from app.database import get_db

        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        month_str = today.strftime("%Y-%m")
        claim_ids = []

        try:
            # Create some claims with different types and statuses
            for i, (ctype, desc) in enumerate([
                ("ASSIGNMENT_WORK", "E2E summary claim 1"),
                ("TRAVEL", "E2E summary claim 2"),
                ("MEETING", "E2E summary claim 3"),
            ]):
                response = session.post(
                    f"{base_url}/utilization/new",
                    data={
                        "activity_date": today_str,
                        "claim_type": ctype,
                        "man_days_claimed": 1.0 + i,
                        "activity_description": desc,
                        "event_duration_days": 1.0 + i if ctype == "MEETING" else 0,
                    },
                    allow_redirects=False,
                )
                assert response.status_code == 302

                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id FROM utilization_claims WHERE activity_description = ?",
                        (desc,),
                    )
                    row = cursor.fetchone()
                    if row:
                        claim_ids.append(row["id"])

            # Submit one claim and TL-approve it so it shows in summary
            if claim_ids:
                session.post(f"{base_url}/utilization/{claim_ids[0]}/submit", allow_redirects=True)
                session.post(
                    f"{base_url}/utilization/{claim_ids[0]}/tl-approve",
                    data={"remarks": ""},
                    allow_redirects=True,
                )

            # View summary page
            response = session.get(f"{base_url}/utilization/summary?month={month_str}")
            assert response.status_code == 200
            # The summary page should render with officer data
            assert "summary" in response.text.lower() or "utilization" in response.text.lower()

            # View pending approval page (TL view)
            response = session.get(f"{base_url}/utilization/pending-approval")
            assert response.status_code == 200

            # View pending rectification page (Head view)
            response = session.get(f"{base_url}/utilization/pending-rectification")
            assert response.status_code == 200

        finally:
            with get_db() as conn:
                cursor = conn.cursor()
                for cid in claim_ids:
                    cursor.execute("DELETE FROM utilization_claims WHERE id = ?", (cid,))
