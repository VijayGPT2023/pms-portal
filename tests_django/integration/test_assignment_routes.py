"""
Integration tests for assignment routes.
"""
from datetime import date, timedelta

import pytest
from django.test import Client as TestClient
from core.models import (
    Assignment, InvoiceRequest, Milestone, PaymentReceipt, SiteConfig,
)

pytestmark = pytest.mark.django_db


class TestAssignmentPages:
    def test_register_activity_requires_auth(self):
        client = TestClient()
        response = client.get("/assignment/register/")
        assert response.status_code == 302

    def test_register_activity_loads(self, auth_client):
        response = auth_client.get("/assignment/register/")
        assert response.status_code == 200

    def test_workorders_list_loads(self, auth_client):
        response = auth_client.get("/assignment/workorders/")
        assert response.status_code == 200

    def test_select_activity_type_loads(self, auth_client):
        response = auth_client.get("/assignment/select-activity-type/")
        assert response.status_code == 200

    def test_view_assignment(self, auth_client, sample_assignment):
        response = auth_client.get(f"/assignment/view/{sample_assignment.id}/")
        assert response.status_code == 200

    def test_view_nonexistent_assignment_404(self, auth_client):
        response = auth_client.get("/assignment/view/99999/")
        assert response.status_code == 404

    def test_assignments_list_loads(self, auth_client):
        response = auth_client.get("/mis/assignments/")
        assert response.status_code == 200


class TestAssignmentRegistration:
    def test_register_creates_draft(self, auth_client, office):
        response = auth_client.post("/assignment/register/", {
            "title": "New Study",
            "office_id": "HQ",
        })
        assert response.status_code == 302
        a = Assignment.objects.filter(title="New Study").first()
        assert a is not None
        # View auto-submits registration, so status is PENDING_APPROVAL
        assert a.registration_status in ("DRAFT", "PENDING_APPROVAL")
        assert a.workflow_stage == "REGISTRATION"


class TestMilestones:
    def test_milestones_page_loads(self, auth_client, sample_assignment):
        response = auth_client.get(f"/assignment/milestones/{sample_assignment.id}/")
        assert response.status_code == 200

    def test_add_milestone(self, auth_client, sample_assignment):
        response = auth_client.post(f"/assignment/milestones/{sample_assignment.id}/", {
            "milestone_count": "1",
            "title_1": "First Milestone",
            "target_date_1": "2026-06-30",
            "invoice_percent_1": "100",
        })
        assert response.status_code == 302


class TestExpenditure:
    def test_expenditure_page_loads(self, auth_client, sample_assignment):
        response = auth_client.get(f"/assignment/expenditure/{sample_assignment.id}/")
        assert response.status_code == 200


class TestRetrospectiveFill:
    """SCOPE_V2 §3.6 — retrospective data entry for bulk-onboarded assignments."""

    def test_requires_auth(self, sample_assignment):
        client = TestClient()
        response = client.get(f"/assignment/retrospective-fill/{sample_assignment.id}/")
        assert response.status_code == 302  # login redirect

    def test_redirects_when_not_bulk_onboarded(self, auth_client, sample_assignment):
        assert sample_assignment.is_bulk_onboarded is False
        response = auth_client.get(f"/assignment/retrospective-fill/{sample_assignment.id}/")
        assert response.status_code == 302

    def test_loads_for_bulk_onboarded(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.get(f"/assignment/retrospective-fill/{sample_assignment.id}/")
        assert response.status_code == 200
        assert b"Retrospective Data Entry" in response.content

    def test_post_saves_as_of_date_and_physical_percent(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"as_of_date": "2026-03-31", "physical_progress_percent": "65.5"},
        )
        assert response.status_code == 302
        sample_assignment.refresh_from_db()
        assert str(sample_assignment.bulk_onboarding_as_of_date) == "2026-03-31"
        assert sample_assignment.physical_progress_percent == 65.5

    def test_post_rejects_out_of_range_percent(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"physical_progress_percent": "150"},
        )
        assert response.status_code == 302
        sample_assignment.refresh_from_db()
        assert sample_assignment.physical_progress_percent == 0  # unchanged


class TestRetrospectiveHistoricInvoice:
    """D.2 — historic invoice capture bypasses FSM (approved=A1)."""

    def _bulk(self, assignment):
        assignment.is_bulk_onboarded = True
        assignment.save(update_fields=["is_bulk_onboarded"])

    def test_add_invoice_creates_invoiced_record_with_80_revenue(self, auth_client, sample_assignment):
        self._bulk(sample_assignment)
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {
                "action": "add_invoice",
                "invoice_date": "2025-09-15",
                "invoice_amount": "100000",
                "invoice_type": "SUBSEQUENT",
                "invoice_reference": "NPC-INV-2025-42",
            },
        )
        assert response.status_code == 302
        inv = InvoiceRequest.objects.get(assignment=sample_assignment)
        assert inv.status == "INVOICED"  # FSM bypassed
        assert inv.invoice_amount == 100000
        assert inv.revenue_recognized_80 == 80000.0
        assert inv.fy_period == "2025-26"  # Sep-2025 falls in Indian FY 2025-26
        assert str(inv.tally_invoice_date) == "2025-09-15"
        assert inv.request_number.startswith("LEGACY/")

    def test_add_invoice_updates_cached_invoice_amount(self, auth_client, sample_assignment):
        self._bulk(sample_assignment)
        auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"action": "add_invoice", "invoice_date": "2025-09-15", "invoice_amount": "50000"},
        )
        sample_assignment.refresh_from_db()
        assert sample_assignment.invoice_amount == 50000

    def test_add_invoice_rejects_non_positive(self, auth_client, sample_assignment):
        self._bulk(sample_assignment)
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"action": "add_invoice", "invoice_date": "2025-09-15", "invoice_amount": "0"},
        )
        assert response.status_code == 302
        assert InvoiceRequest.objects.filter(assignment=sample_assignment).count() == 0

    def test_fy_derivation_crosses_financial_year(self, auth_client, sample_assignment):
        """Indian FY: Apr-Mar. A Feb date falls in the previous calendar year's FY."""
        self._bulk(sample_assignment)
        auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {"action": "add_invoice", "invoice_date": "2026-02-10", "invoice_amount": "1"},
        )
        inv = InvoiceRequest.objects.get(assignment=sample_assignment)
        assert inv.fy_period == "2025-26"  # Feb-2026 is still FY 2025-26


class TestRetrospectiveHistoricPayment:
    """D.2 — historic payment capture. 20% revenue via existing save() override."""

    def _bulk_with_invoice(self, auth_client, assignment):
        assignment.is_bulk_onboarded = True
        assignment.save(update_fields=["is_bulk_onboarded"])
        auth_client.post(
            f"/assignment/retrospective-fill/{assignment.id}/",
            {"action": "add_invoice", "invoice_date": "2025-09-15", "invoice_amount": "100000"},
        )
        return InvoiceRequest.objects.get(assignment=assignment)

    def test_add_payment_creates_receipt_with_20_revenue(self, auth_client, sample_assignment):
        inv = self._bulk_with_invoice(auth_client, sample_assignment)
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {
                "action": "add_payment",
                "invoice_id": str(inv.id),
                "payment_date": "2025-10-20",
                "payment_amount": "100000",
                "payment_mode": "NEFT",
                "payment_reference": "UTR123",
            },
        )
        assert response.status_code == 302
        pr = PaymentReceipt.objects.get(invoice_request=inv)
        assert pr.amount_received == 100000
        assert pr.revenue_recognized_20 == 20000.0  # auto via save() override
        assert pr.payment_mode == "NEFT"
        assert pr.reference_number == "UTR123"
        assert pr.fy_period == "2025-26"
        assert pr.receipt_number.startswith("LEGACY/")

    def test_add_payment_updates_cached_amount_received(self, auth_client, sample_assignment):
        inv = self._bulk_with_invoice(auth_client, sample_assignment)
        auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {
                "action": "add_payment",
                "invoice_id": str(inv.id),
                "payment_date": "2025-10-20",
                "payment_amount": "75000",
            },
        )
        sample_assignment.refresh_from_db()
        assert sample_assignment.amount_received == 75000

    def test_add_payment_rejects_invalid_invoice(self, auth_client, sample_assignment):
        sample_assignment.is_bulk_onboarded = True
        sample_assignment.save(update_fields=["is_bulk_onboarded"])
        response = auth_client.post(
            f"/assignment/retrospective-fill/{sample_assignment.id}/",
            {
                "action": "add_payment",
                "invoice_id": "99999",
                "payment_date": "2025-10-20",
                "payment_amount": "1000",
            },
        )
        assert response.status_code == 302
        assert PaymentReceipt.objects.count() == 0


class TestBulkOnboardingWindowGate:
    """SCOPE_V2 §3.6 — window gate controls is_bulk_onboarded flagging on confirm."""

    def test_confirm_flags_bulk_when_window_open(self, auth_client, sample_assignment):
        # Window has never been configured → open by default.
        response = auth_client.post("/head/assignments/", {
            "action": "confirm",
            "assignment_id": str(sample_assignment.id),
        })
        assert response.status_code == 302
        sample_assignment.refresh_from_db()
        assert sample_assignment.is_bulk_onboarded is True

    def test_confirm_does_not_flag_when_window_closed(self, auth_client, sample_assignment):
        past = (date.today() - timedelta(days=1)).isoformat()
        SiteConfig.set(SiteConfig.KEY_BULK_WINDOW_CLOSE, past)
        response = auth_client.post("/head/assignments/", {
            "action": "confirm",
            "assignment_id": str(sample_assignment.id),
        })
        assert response.status_code == 302
        sample_assignment.refresh_from_db()
        assert sample_assignment.is_bulk_onboarded is False
        # But the approval still happened — confirm still advances the assignment.
        assert sample_assignment.registration_status == "APPROVED"
        assert sample_assignment.approval_status == "APPROVED"

    def test_head_hub_shows_window_status(self, auth_client):
        response = auth_client.get("/head/assignments/")
        assert response.status_code == 200
        assert b"Bulk Onboarding Window" in response.content
