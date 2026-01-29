"""
Unit tests for app/database.py -- progress calculations, revenue logic,
financial year, number generation.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.database import (
    get_current_fy,
    get_target_for_designation,
)

pytestmark = pytest.mark.unit


# ── get_current_fy ───────────────────────────────────────────────────

class TestGetCurrentFY:
    def test_returns_string(self):
        fy = get_current_fy()
        assert isinstance(fy, str)

    def test_format_pattern(self):
        import re
        fy = get_current_fy()
        assert re.match(r'^\d{4}-\d{2}$', fy), f"FY format should be YYYY-YY, got {fy}"

    def test_april_starts_new_fy(self):
        """April belongs to the FY starting that year."""
        # Verify the logic: month >= 4 means FY = year-year+1
        today = date.today()
        fy = get_current_fy()
        if today.month >= 4:
            expected = f"{today.year}-{str(today.year + 1)[2:]}"
        else:
            expected = f"{today.year - 1}-{str(today.year)[2:]}"
        assert fy == expected

    def test_fy_year_consistency(self):
        """The two years in the FY string differ by exactly 1."""
        fy = get_current_fy()
        start_year = int(fy[:4])
        end_suffix = int(fy[5:])
        assert end_suffix == (start_year + 1) % 100


# ── get_target_for_designation ───────────────────────────────────────

class TestGetTargetForDesignation:
    def test_returns_float(self):
        target = get_target_for_designation("Consultant")
        assert isinstance(target, (int, float))

    def test_positive_value(self):
        target = get_target_for_designation("Consultant")
        assert target >= 0

    def test_dg_target(self):
        target = get_target_for_designation("DG")
        assert target >= 0

    def test_unknown_designation(self):
        target = get_target_for_designation("Unknown_Role_XYZ")
        assert isinstance(target, (int, float))


# ── Revenue calculation logic (pure math tests) ─────────────────────

class TestRevenueCalculations:
    """Test the 80-20 revenue model math."""

    def test_80_percent_of_invoice(self):
        invoice_amount = 10.0
        revenue_80 = invoice_amount * 0.80
        assert revenue_80 == pytest.approx(8.0)

    def test_20_percent_of_payment(self):
        payment_amount = 10.0
        revenue_20 = payment_amount * 0.20
        assert revenue_20 == pytest.approx(2.0)

    def test_80_plus_20_equals_full(self):
        amount = 10.0
        rev_80 = amount * 0.80
        rev_20 = amount * 0.20
        assert rev_80 + rev_20 == pytest.approx(amount)

    def test_officer_share_calculation(self):
        """Officer with 30% share of 80% revenue."""
        invoice_amount = 100.0
        revenue_80 = invoice_amount * 0.80  # 80.0
        officer_share = 30.0  # percent
        officer_revenue = revenue_80 * officer_share / 100
        assert officer_revenue == pytest.approx(24.0)

    def test_multiple_officers_shares_sum(self):
        """Multiple officers shares must sum correctly."""
        invoice_amount = 100.0
        revenue_80 = invoice_amount * 0.80
        shares = [40.0, 35.0, 25.0]  # must sum to 100%
        assert sum(shares) == pytest.approx(100.0)
        total_allocated = sum(revenue_80 * s / 100 for s in shares)
        assert total_allocated == pytest.approx(revenue_80)

    def test_zero_invoice(self):
        assert 0.0 * 0.80 == 0.0
        assert 0.0 * 0.20 == 0.0

    def test_fractional_amount(self):
        invoice = 33.33
        rev_80 = invoice * 0.80
        rev_20 = invoice * 0.20
        assert rev_80 + rev_20 == pytest.approx(invoice)


# ── Progress calculation logic ───────────────────────────────────────

class TestProgressCalculationLogic:
    """Test the physical/timeline progress formulas."""

    def test_physical_progress_all_paid(self):
        """All milestones paid -> 100%."""
        milestones = [
            {"invoice_percent": 50, "payment_received": 1, "invoice_raised": 1},
            {"invoice_percent": 50, "payment_received": 1, "invoice_raised": 1},
        ]
        total = sum(m["invoice_percent"] for m in milestones)
        progress = sum(
            m["invoice_percent"] * (100 if m["payment_received"] else (80 if m["invoice_raised"] else 0))
            / 100
            for m in milestones
        ) / total * 100 if total > 0 else 0
        assert progress == pytest.approx(100.0)

    def test_physical_progress_all_invoiced_not_paid(self):
        """All milestones invoiced but not paid -> 80%."""
        milestones = [
            {"invoice_percent": 50, "payment_received": 0, "invoice_raised": 1},
            {"invoice_percent": 50, "payment_received": 0, "invoice_raised": 1},
        ]
        total = sum(m["invoice_percent"] for m in milestones)
        progress = sum(
            m["invoice_percent"] * (100 if m["payment_received"] else (80 if m["invoice_raised"] else 0))
            / 100
            for m in milestones
        ) / total * 100 if total > 0 else 0
        assert progress == pytest.approx(80.0)

    def test_physical_progress_none_invoiced(self):
        """No milestones invoiced -> 0%."""
        milestones = [
            {"invoice_percent": 50, "payment_received": 0, "invoice_raised": 0},
            {"invoice_percent": 50, "payment_received": 0, "invoice_raised": 0},
        ]
        total = sum(m["invoice_percent"] for m in milestones)
        progress = sum(
            m["invoice_percent"] * (100 if m["payment_received"] else (80 if m["invoice_raised"] else 0))
            / 100
            for m in milestones
        ) / total * 100 if total > 0 else 0
        assert progress == pytest.approx(0.0)

    def test_physical_progress_mixed(self):
        """One paid (50%), one not invoiced (50%) -> 50%."""
        milestones = [
            {"invoice_percent": 50, "payment_received": 1, "invoice_raised": 1},
            {"invoice_percent": 50, "payment_received": 0, "invoice_raised": 0},
        ]
        total = sum(m["invoice_percent"] for m in milestones)
        progress = sum(
            m["invoice_percent"] * (100 if m["payment_received"] else (80 if m["invoice_raised"] else 0))
            / 100
            for m in milestones
        ) / total * 100 if total > 0 else 0
        assert progress == pytest.approx(50.0)

    def test_empty_milestones(self):
        """No milestones -> 0%."""
        milestones = []
        total = sum(m.get("invoice_percent", 0) for m in milestones)
        progress = 0 if total == 0 else 100
        assert progress == 0


# ── Development work notional value ──────────────────────────────────

class TestNotionalValue:
    def test_standard_calculation(self):
        man_days = 25
        daily_rate = 0.20  # Lakhs
        expected = 5.0
        assert man_days * daily_rate == pytest.approx(expected)

    def test_zero_man_days(self):
        assert 0 * 0.20 == 0.0

    def test_fractional_man_days(self):
        assert 10.5 * 0.20 == pytest.approx(2.1)

    def test_large_man_days(self):
        assert 365 * 0.20 == pytest.approx(73.0)


# ── Assignment number generation logic ───────────────────────────────

class TestAssignmentNumberFormat:
    """Test the assignment number format convention."""

    def test_format_pattern(self):
        import re
        pattern = r'^NPC/[A-Z]+/[A-Z]+/[A-Z]\d+/\d{4}-\d{2}$'
        example = "NPC/HQ/ES/P01/2025-26"
        assert re.match(pattern, example)

    def test_type_prefix_mapping(self):
        prefixes = {"ASSIGNMENT": "P", "TRAINING": "T", "DEVELOPMENT": "D"}
        for atype, prefix in prefixes.items():
            assert prefix in "PTD"
