"""
Unit tests for new config settings added in Phase 2 -- feature flags,
revenue weightage, dev work quantification, uploads, activity codes,
utilization claim types.
"""
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.config import (
    SHOW_RANKINGS,
    TRAINING_MODE,
    REVENUE_WEIGHTAGE_REAL,
    REVENUE_WEIGHTAGE_NOTIONAL,
    DEV_WORK_QUANTIFICATION,
    UPLOAD_DIR,
    MAX_UPLOAD_SIZE_MB,
    ALLOWED_UPLOAD_EXTENSIONS,
    ACTIVITY_TYPE_CODES,
    UTILIZATION_CLAIM_TYPES,
    CLIENT_TYPE_OPTIONS,
)

pytestmark = pytest.mark.unit


# ── Feature flags ──────────────────────────────────────────────────

class TestFeatureFlags:
    def test_show_rankings_default_false(self):
        assert SHOW_RANKINGS is False

    def test_training_mode_default_true(self):
        assert TRAINING_MODE is True

    def test_show_rankings_is_bool(self):
        assert isinstance(SHOW_RANKINGS, bool)

    def test_training_mode_is_bool(self):
        assert isinstance(TRAINING_MODE, bool)


# ── Revenue weightage ─────────────────────────────────────────────

class TestRevenueWeightage:
    def test_real_weightage(self):
        assert REVENUE_WEIGHTAGE_REAL == 1.0

    def test_notional_weightage(self):
        assert REVENUE_WEIGHTAGE_NOTIONAL == 0.5

    def test_real_greater_than_notional(self):
        assert REVENUE_WEIGHTAGE_REAL > REVENUE_WEIGHTAGE_NOTIONAL

    def test_weightages_are_float(self):
        assert isinstance(REVENUE_WEIGHTAGE_REAL, (int, float))
        assert isinstance(REVENUE_WEIGHTAGE_NOTIONAL, (int, float))


# ── Development Work Quantification ───────────────────────────────

class TestDevWorkQuantification:
    def test_has_proposal_prep(self):
        assert 'PROPOSAL_PREP' in DEV_WORK_QUANTIFICATION

    def test_has_event_mgmt(self):
        assert 'EVENT_MGMT' in DEV_WORK_QUANTIFICATION

    def test_has_committee(self):
        assert 'COMMITTEE' in DEV_WORK_QUANTIFICATION

    def test_has_meeting(self):
        assert 'MEETING' in DEV_WORK_QUANTIFICATION

    def test_proposal_prep_has_slabs(self):
        assert 'slabs' in DEV_WORK_QUANTIFICATION['PROPOSAL_PREP']

    def test_proposal_prep_slabs_count(self):
        slabs = DEV_WORK_QUANTIFICATION['PROPOSAL_PREP']['slabs']
        assert len(slabs) == 5

    def test_proposal_prep_slab_values(self):
        slabs = DEV_WORK_QUANTIFICATION['PROPOSAL_PREP']['slabs']
        expected = [(20, 1), (50, 2), (100, 3), (200, 4), (float('inf'), 5)]
        assert slabs == expected

    def test_proposal_prep_slabs_ascending_thresholds(self):
        slabs = DEV_WORK_QUANTIFICATION['PROPOSAL_PREP']['slabs']
        thresholds = [s[0] for s in slabs]
        for i in range(len(thresholds) - 1):
            assert thresholds[i] < thresholds[i + 1]

    def test_proposal_prep_slabs_ascending_days(self):
        slabs = DEV_WORK_QUANTIFICATION['PROPOSAL_PREP']['slabs']
        days = [s[1] for s in slabs]
        for i in range(len(days) - 1):
            assert days[i] < days[i + 1]

    def test_event_mgmt_max_days(self):
        assert DEV_WORK_QUANTIFICATION['EVENT_MGMT']['max_days'] == 5

    def test_committee_per_member_days(self):
        assert DEV_WORK_QUANTIFICATION['COMMITTEE']['per_member_days'] == 0.25

    def test_meeting_min_days(self):
        assert DEV_WORK_QUANTIFICATION['MEETING']['min_days'] == 0.5


# ── Upload settings ───────────────────────────────────────────────

class TestUploadSettings:
    def test_upload_dir_is_path(self):
        assert isinstance(UPLOAD_DIR, Path)

    def test_max_upload_size(self):
        assert MAX_UPLOAD_SIZE_MB == 10

    def test_max_upload_size_positive(self):
        assert MAX_UPLOAD_SIZE_MB > 0

    def test_allowed_extensions_has_pdf(self):
        assert '.pdf' in ALLOWED_UPLOAD_EXTENSIONS

    def test_allowed_extensions_has_doc(self):
        assert '.doc' in ALLOWED_UPLOAD_EXTENSIONS

    def test_allowed_extensions_has_docx(self):
        assert '.docx' in ALLOWED_UPLOAD_EXTENSIONS

    def test_allowed_extensions_is_list(self):
        assert isinstance(ALLOWED_UPLOAD_EXTENSIONS, list)

    def test_all_extensions_start_with_dot(self):
        for ext in ALLOWED_UPLOAD_EXTENSIONS:
            assert ext.startswith('.'), f"Extension {ext} should start with a dot"


# ── Activity type codes ───────────────────────────────────────────

class TestActivityTypeCodes:
    def test_has_assignment(self):
        assert 'ASSIGNMENT' in ACTIVITY_TYPE_CODES

    def test_has_training(self):
        assert 'TRAINING' in ACTIVITY_TYPE_CODES

    def test_has_development(self):
        assert 'DEVELOPMENT' in ACTIVITY_TYPE_CODES

    def test_assignment_code(self):
        assert ACTIVITY_TYPE_CODES['ASSIGNMENT'] == 'ASG'

    def test_training_code(self):
        assert ACTIVITY_TYPE_CODES['TRAINING'] == 'TRG'

    def test_development_code(self):
        assert ACTIVITY_TYPE_CODES['DEVELOPMENT'] == 'DEV'

    def test_codes_are_strings(self):
        for key, code in ACTIVITY_TYPE_CODES.items():
            assert isinstance(code, str)
            assert len(code) > 0


# ── Utilization claim types ───────────────────────────────────────

class TestUtilizationClaimTypes:
    def test_is_list(self):
        assert isinstance(UTILIZATION_CLAIM_TYPES, list)

    def test_has_entries(self):
        assert len(UTILIZATION_CLAIM_TYPES) >= 5

    def test_all_tuples(self):
        for item in UTILIZATION_CLAIM_TYPES:
            assert isinstance(item, tuple), f"{item} should be a tuple"
            assert len(item) == 2, f"Tuple {item} should have 2 elements (code, label)"

    def test_contains_assignment_work(self):
        codes = [ct[0] for ct in UTILIZATION_CLAIM_TYPES]
        assert 'ASSIGNMENT_WORK' in codes

    def test_contains_proposal_prep(self):
        codes = [ct[0] for ct in UTILIZATION_CLAIM_TYPES]
        assert 'PROPOSAL_PREP' in codes

    def test_contains_event_mgmt(self):
        codes = [ct[0] for ct in UTILIZATION_CLAIM_TYPES]
        assert 'EVENT_MGMT' in codes

    def test_contains_committee(self):
        codes = [ct[0] for ct in UTILIZATION_CLAIM_TYPES]
        assert 'COMMITTEE' in codes

    def test_contains_meeting(self):
        codes = [ct[0] for ct in UTILIZATION_CLAIM_TYPES]
        assert 'MEETING' in codes

    def test_labels_are_strings(self):
        for code, label in UTILIZATION_CLAIM_TYPES:
            assert isinstance(label, str)
            assert len(label) > 0


# ── Client type options ───────────────────────────────────────────

class TestClientTypeOptionsList:
    def test_is_list(self):
        assert isinstance(CLIENT_TYPE_OPTIONS, list)

    def test_has_entries(self):
        assert len(CLIENT_TYPE_OPTIONS) >= 4

    def test_contains_central_govt(self):
        assert "Central Government" in CLIENT_TYPE_OPTIONS

    def test_contains_state_govt(self):
        assert "State Government" in CLIENT_TYPE_OPTIONS

    def test_contains_psu(self):
        assert "PSU" in CLIENT_TYPE_OPTIONS

    def test_contains_private(self):
        assert "Private" in CLIENT_TYPE_OPTIONS

    def test_all_strings(self):
        for opt in CLIENT_TYPE_OPTIONS:
            assert isinstance(opt, str)
