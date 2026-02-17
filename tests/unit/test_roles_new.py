"""
Unit tests for FINANCE role, new permissions, and finance-related helper
functions added in Phase 2 of app/roles.py.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.roles import (
    ROLE_FINANCE, ROLE_ADMIN, ROLE_DG, ROLE_TEAM_LEADER, ROLE_OFFICER,
    ALL_ROLES, ROLE_PERMISSIONS, ROLE_NAMES,
    PERM_APPROVE_INVOICE, PERM_RECORD_PAYMENT, PERM_MANAGE_FINANCE,
    PERM_VIEW_OFFICE_MIS, PERM_DOWNLOAD_REPORTS,
    is_finance_officer, is_finance_for_office,
    has_permission, get_user_permissions, get_role_display_name,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from __mocks__.fixtures import make_user, OFFICER_USER, ADMIN_USER

pytestmark = pytest.mark.unit


def _mock_db():
    """Return a patch for app.database.get_db that returns an empty cursor."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    p = patch("app.database.get_db")
    m = p.start()
    m.return_value.__enter__ = MagicMock(return_value=mock_conn)
    m.return_value.__exit__ = MagicMock(return_value=False)
    return p, mock_cursor


# Shared fixture for a finance user
FINANCE_USER = make_user(
    officer_id="FIN001",
    name="Finance Officer",
    email="finance@npcindia.gov.in",
    role="FINANCE",
    admin_role_id="FINANCE",
    permissions=[
        "view_office_mis", "approve_invoice", "record_payment",
        "manage_finance", "download_reports",
    ],
)


# ── FINANCE role in hierarchy ─────────────────────────────────────

class TestFinanceRoleConstants:
    def test_finance_role_exists_in_all_roles(self):
        assert ROLE_FINANCE in ALL_ROLES

    def test_all_roles_now_has_nine(self):
        assert len(ALL_ROLES) == 9

    def test_finance_between_tl_and_officer(self):
        tl_idx = ALL_ROLES.index(ROLE_TEAM_LEADER)
        fin_idx = ALL_ROLES.index(ROLE_FINANCE)
        off_idx = ALL_ROLES.index(ROLE_OFFICER)
        assert tl_idx < fin_idx < off_idx

    def test_finance_role_has_display_name(self):
        assert ROLE_FINANCE in ROLE_NAMES
        assert ROLE_NAMES[ROLE_FINANCE] == 'Finance Officer'

    def test_get_role_display_name_finance(self):
        name = get_role_display_name(ROLE_FINANCE)
        assert name == 'Finance Officer'


# ── FINANCE permissions ───────────────────────────────────────────

class TestFinancePermissions:
    def test_finance_has_approve_invoice(self):
        assert PERM_APPROVE_INVOICE in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_has_record_payment(self):
        assert PERM_RECORD_PAYMENT in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_has_manage_finance(self):
        assert PERM_MANAGE_FINANCE in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_has_download_reports(self):
        assert PERM_DOWNLOAD_REPORTS in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_has_view_office_mis(self):
        assert PERM_VIEW_OFFICE_MIS in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_does_not_have_manage_users(self):
        assert 'manage_users' not in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_does_not_have_approve_assignment(self):
        assert 'approve_assignment' not in ROLE_PERMISSIONS[ROLE_FINANCE]

    def test_finance_permissions_count(self):
        perms = ROLE_PERMISSIONS[ROLE_FINANCE]
        assert len(perms) == 5

    def test_officer_does_not_have_approve_invoice(self):
        assert PERM_APPROVE_INVOICE not in ROLE_PERMISSIONS[ROLE_OFFICER]

    def test_officer_does_not_have_record_payment(self):
        assert PERM_RECORD_PAYMENT not in ROLE_PERMISSIONS[ROLE_OFFICER]


# ── is_finance_officer ────────────────────────────────────────────

class TestIsFinanceOfficer:
    def setup_method(self):
        self._patch, self._cursor = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_finance_user_returns_true(self):
        assert is_finance_officer(FINANCE_USER) is True

    def test_regular_officer_returns_false(self):
        assert is_finance_officer(OFFICER_USER) is False

    def test_admin_returns_false(self):
        assert is_finance_officer(ADMIN_USER) is False

    def test_empty_user_returns_false(self):
        assert is_finance_officer({}) is False

    def test_none_role_returns_false(self):
        user = make_user(role=None, admin_role_id=None)
        assert is_finance_officer(user) is False


# ── is_finance_for_office ─────────────────────────────────────────

class TestIsFinanceForOffice:
    def setup_method(self):
        self._patch, self._cursor = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_returns_true_when_record_exists(self):
        self._cursor.fetchone.return_value = {"id": 1}
        result = is_finance_for_office(FINANCE_USER, "HQ")
        assert result is True

    def test_returns_false_when_no_record(self):
        self._cursor.fetchone.return_value = None
        result = is_finance_for_office(FINANCE_USER, "HQ")
        assert result is False

    def test_returns_false_for_empty_user(self):
        result = is_finance_for_office({}, "HQ")
        assert result is False

    def test_returns_false_for_none_user(self):
        result = is_finance_for_office(None, "HQ")
        assert result is False

    def test_queries_correct_table(self):
        self._cursor.fetchone.return_value = None
        is_finance_for_office(FINANCE_USER, "RDDEL")
        # Verify execute was called with a query referencing finance_officers
        call_args = self._cursor.execute.call_args
        assert "finance_officers" in call_args[0][0]


# ── has_permission for FINANCE role ───────────────────────────────

class TestFinanceHasPermission:
    def setup_method(self):
        self._patch, self._cursor = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_finance_has_approve_invoice(self):
        assert has_permission(FINANCE_USER, PERM_APPROVE_INVOICE) is True

    def test_finance_has_record_payment(self):
        assert has_permission(FINANCE_USER, PERM_RECORD_PAYMENT) is True

    def test_finance_has_manage_finance(self):
        assert has_permission(FINANCE_USER, PERM_MANAGE_FINANCE) is True

    def test_finance_no_manage_users(self):
        assert has_permission(FINANCE_USER, 'manage_users') is False

    def test_finance_no_approve_assignment(self):
        assert has_permission(FINANCE_USER, 'approve_assignment') is False


# ── get_user_permissions for FINANCE ──────────────────────────────

class TestFinanceGetUserPermissions:
    def setup_method(self):
        self._patch, self._cursor = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_includes_finance_permissions(self):
        perms = get_user_permissions(FINANCE_USER)
        assert PERM_APPROVE_INVOICE in perms
        assert PERM_RECORD_PAYMENT in perms
        assert PERM_MANAGE_FINANCE in perms

    def test_includes_download_reports(self):
        perms = get_user_permissions(FINANCE_USER)
        assert PERM_DOWNLOAD_REPORTS in perms
