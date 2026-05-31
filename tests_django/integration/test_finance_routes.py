"""
Integration tests for finance routes — invoicing and 80-20 revenue model.
"""
import pytest
from django.test import Client as TestClient
from core.models import InvoiceRequest, PaymentReceipt, OfficerRevenueLedger

pytestmark = pytest.mark.django_db


class TestFinanceDashboard:
    def test_finance_dashboard_requires_auth(self):
        client = TestClient()
        response = client.get("/finance/")
        assert response.status_code == 302

    def test_finance_dashboard_loads(self, auth_client):
        response = auth_client.get("/finance/")
        assert response.status_code == 200
        assert b"Finance Dashboard" in response.content
        assert b"coming soon" not in response.content

    def test_approved_invoice_status_renders(self, auth_client, sample_assignment, officer_user):
        """Guard: InvoiceRequest.status is an FSMField (no get_status_display);
        the dashboard must render the raw status value, not blank."""
        InvoiceRequest.objects.create(
            request_number="INV-STATUS-001", assignment=sample_assignment,
            invoice_amount=100.0, fy_period="2025-26",
            requested_by=officer_user, status="APPROVED",
        )
        response = auth_client.get("/finance/")
        assert response.status_code == 200
        assert b"INV-STATUS-001" in response.content
        assert b"APPROVED" in response.content  # status visible, not blank  # real template, not stub


class TestInvoiceRequest:
    def test_invoice_form_loads(self, auth_client, sample_assignment):
        response = auth_client.get(f"/finance/invoice-request/{sample_assignment.id}/")
        assert response.status_code == 200
        assert b"Raise Invoice Request" in response.content
        assert b"coming soon" not in response.content


class TestPayment:
    def test_payment_form_loads(self, auth_client, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="INV-FIN-001",
            assignment=sample_assignment,
            invoice_amount=100.0,
            fy_period="2025-26",
            requested_by=officer_user,
            status="APPROVED",
        )
        response = auth_client.get(f"/finance/payment/{inv.id}/")
        assert response.status_code == 200
        assert b"Record Payment" in response.content
        assert b"coming soon" not in response.content


class TestRevenueModel:
    """Test the 80-20 revenue recognition model end-to-end."""

    def test_80_percent_on_invoice_approval(self, db, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="REV-001",
            assignment=sample_assignment,
            invoice_amount=100.0,
            fy_period="2025-26",
            requested_by=officer_user,
        )
        inv.approve()
        inv.save()
        assert inv.revenue_recognized_80 == 80.0

    def test_20_percent_on_payment_receipt(self, db, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="REV-002",
            assignment=sample_assignment,
            invoice_amount=100.0,
            fy_period="2025-26",
            requested_by=officer_user,
            status="APPROVED",
        )
        pmt = PaymentReceipt.objects.create(
            receipt_number="PMT-REV-001",
            invoice_request=inv,
            amount_received=100.0,
            receipt_date="2025-12-01",
            fy_period="2025-26",
            updated_by=officer_user,
        )
        assert pmt.revenue_recognized_20 == 20.0

    def test_total_revenue_100_percent(self, db, sample_assignment, officer_user):
        inv = InvoiceRequest.objects.create(
            request_number="REV-003",
            assignment=sample_assignment,
            invoice_amount=100.0,
            fy_period="2025-26",
            requested_by=officer_user,
        )
        inv.approve()
        inv.save()

        pmt = PaymentReceipt.objects.create(
            receipt_number="PMT-REV-002",
            invoice_request=inv,
            amount_received=100.0,
            receipt_date="2025-12-01",
            fy_period="2025-26",
            updated_by=officer_user,
        )

        total = inv.revenue_recognized_80 + pmt.revenue_recognized_20
        assert total == 100.0  # 80 + 20 = 100


class TestSurplusSharing:
    """Revenue is shared on SURPLUS (billed − direct expenditure), not gross."""

    def test_invoice_80_on_surplus(self, db, sample_assignment, officer_user):
        sample_assignment.total_expenditure = 30.0
        sample_assignment.save(update_fields=["total_expenditure"])
        inv = InvoiceRequest.objects.create(
            request_number="SURP-1", assignment=sample_assignment,
            invoice_amount=100.0, fy_period="2025-26", requested_by=officer_user,
        )
        inv.approve(); inv.save()
        # surplus = 100 − 30 = 70 ; 80% = 56
        assert inv.revenue_recognized_80 == pytest.approx(56.0)

    def test_payment_20_on_surplus(self, db, sample_assignment, officer_user):
        sample_assignment.total_expenditure = 30.0
        sample_assignment.save(update_fields=["total_expenditure"])
        inv = InvoiceRequest.objects.create(
            request_number="SURP-2", assignment=sample_assignment,
            invoice_amount=100.0, fy_period="2025-26", requested_by=officer_user,
            status="APPROVED",
        )
        pmt = PaymentReceipt.objects.create(
            receipt_number="SURP-PMT-1", invoice_request=inv, amount_received=100.0,
            receipt_date="2025-12-01", fy_period="2025-26", updated_by=officer_user,
        )
        # surplus = 100 − 30 = 70 ; 20% = 14
        assert pmt.revenue_recognized_20 == pytest.approx(14.0)

    def test_surplus_floors_at_zero(self, db, sample_assignment, officer_user):
        sample_assignment.total_expenditure = 150.0  # exceeds invoice
        sample_assignment.save(update_fields=["total_expenditure"])
        inv = InvoiceRequest.objects.create(
            request_number="SURP-3", assignment=sample_assignment,
            invoice_amount=100.0, fy_period="2025-26", requested_by=officer_user,
        )
        inv.approve(); inv.save()
        assert inv.revenue_recognized_80 == 0.0
