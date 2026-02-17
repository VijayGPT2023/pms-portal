"""
Unit tests for utilization auto-calculation logic from
app/routes/utilization_routes.py -- calculate_auto_days function.

Tests the slab-based quantification rules for PROPOSAL_PREP, EVENT_MGMT,
COMMITTEE, MEETING, and pass-through for unknown types.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.routes.utilization_routes import calculate_auto_days

pytestmark = pytest.mark.unit


# ── PROPOSAL_PREP slab tests ─────────────────────────────────────

class TestProposalPrepSlabs:
    """PROPOSAL_PREP slabs: <=20L→1, <=50L→2, <=100L→3, <=200L→4, >200L→5."""

    def test_value_15_returns_1_day(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=15)
        assert result == 1

    def test_value_20_returns_1_day_boundary(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=20)
        assert result == 1

    def test_value_25_returns_2_days(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=25)
        assert result == 2

    def test_value_50_returns_2_days_boundary(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=50)
        assert result == 2

    def test_value_75_returns_3_days(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=75)
        assert result == 3

    def test_value_100_returns_3_days_boundary(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=100)
        assert result == 3

    def test_value_150_returns_4_days(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=150)
        assert result == 4

    def test_value_200_returns_4_days_boundary(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=200)
        assert result == 4

    def test_value_300_returns_5_days(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=300)
        assert result == 5

    def test_value_1000_returns_5_days(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=1000)
        assert result == 5

    def test_value_zero_returns_1_day(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=0)
        assert result == 1

    def test_value_1_returns_1_day(self):
        result = calculate_auto_days('PROPOSAL_PREP', proposal_value=1)
        assert result == 1


# ── EVENT_MGMT cap tests ─────────────────────────────────────────

class TestEventMgmt:
    """EVENT_MGMT: capped at max_days (5), passes through if <= 5."""

    def test_input_7_capped_at_5(self):
        result = calculate_auto_days('EVENT_MGMT', requested_days=7)
        assert result == 5

    def test_input_10_capped_at_5(self):
        result = calculate_auto_days('EVENT_MGMT', requested_days=10)
        assert result == 5

    def test_input_3_passes_through(self):
        result = calculate_auto_days('EVENT_MGMT', requested_days=3)
        assert result == 3

    def test_input_5_equals_max(self):
        result = calculate_auto_days('EVENT_MGMT', requested_days=5)
        assert result == 5

    def test_input_0_returns_0(self):
        result = calculate_auto_days('EVENT_MGMT', requested_days=0)
        assert result == 0

    def test_input_1_passes_through(self):
        result = calculate_auto_days('EVENT_MGMT', requested_days=1)
        assert result == 1


# ── COMMITTEE per-member calc ─────────────────────────────────────

class TestCommittee:
    """COMMITTEE: 0.25 man-days per member."""

    def test_4_members_returns_1_day(self):
        result = calculate_auto_days('COMMITTEE', num_members=4)
        assert result == pytest.approx(1.0)

    def test_10_members_returns_2_5_days(self):
        result = calculate_auto_days('COMMITTEE', num_members=10)
        assert result == pytest.approx(2.5)

    def test_1_member_returns_0_25(self):
        result = calculate_auto_days('COMMITTEE', num_members=1)
        assert result == pytest.approx(0.25)

    def test_0_members_returns_0(self):
        result = calculate_auto_days('COMMITTEE', num_members=0)
        assert result == pytest.approx(0.0)

    def test_8_members_returns_2(self):
        result = calculate_auto_days('COMMITTEE', num_members=8)
        assert result == pytest.approx(2.0)

    def test_20_members_returns_5(self):
        result = calculate_auto_days('COMMITTEE', num_members=20)
        assert result == pytest.approx(5.0)


# ── MEETING minimum enforcement ───────────────────────────────────

class TestMeeting:
    """MEETING: minimum 0.5 days, passes through if >= 0.5."""

    def test_input_0_25_returns_0_5_min(self):
        result = calculate_auto_days('MEETING', requested_days=0.25)
        assert result == pytest.approx(0.5)

    def test_input_0_returns_0_5_min(self):
        result = calculate_auto_days('MEETING', requested_days=0)
        assert result == pytest.approx(0.5)

    def test_input_1_passes_through(self):
        result = calculate_auto_days('MEETING', requested_days=1.0)
        assert result == pytest.approx(1.0)

    def test_input_0_5_equals_min(self):
        result = calculate_auto_days('MEETING', requested_days=0.5)
        assert result == pytest.approx(0.5)

    def test_input_3_passes_through(self):
        result = calculate_auto_days('MEETING', requested_days=3.0)
        assert result == pytest.approx(3.0)

    def test_input_0_1_returns_0_5_min(self):
        result = calculate_auto_days('MEETING', requested_days=0.1)
        assert result == pytest.approx(0.5)


# ── Unknown / pass-through type ───────────────────────────────────

class TestUnknownClaimType:
    """Unknown claim type returns requested_days as-is."""

    def test_assignment_work_passthrough(self):
        result = calculate_auto_days('ASSIGNMENT_WORK', requested_days=3)
        assert result == 3

    def test_travel_passthrough(self):
        result = calculate_auto_days('TRAVEL', requested_days=2)
        assert result == 2

    def test_leave_passthrough(self):
        result = calculate_auto_days('LEAVE', requested_days=1)
        assert result == 1

    def test_other_passthrough(self):
        result = calculate_auto_days('OTHER', requested_days=4.5)
        assert result == pytest.approx(4.5)

    def test_unknown_type_passthrough(self):
        result = calculate_auto_days('NONEXISTENT', requested_days=7)
        assert result == 7

    def test_zero_days_passthrough(self):
        result = calculate_auto_days('ASSIGNMENT_WORK', requested_days=0)
        assert result == 0
