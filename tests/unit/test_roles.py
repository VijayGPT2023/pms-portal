"""
Unit tests for app/roles.py -- RBAC, permissions, role hierarchy.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.roles import (
    ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II,
    ROLE_RD_HEAD, ROLE_GROUP_HEAD, ROLE_TEAM_LEADER, ROLE_OFFICER,
    ALL_ROLES, ROLE_PERMISSIONS,
    is_admin, is_head, is_senior_management, is_team_leader,
    has_permission, has_any_permission, has_all_permissions,
    get_role_display_name, get_user_permissions,
    can_approve_in_office,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from __mocks__.fixtures import (
    ADMIN_USER, DG_USER, DDG_USER, RD_HEAD_USER,
    GROUP_HEAD_USER, TL_USER, OFFICER_USER, make_user,
)

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
    return p


# ── Role constants ───────────────────────────────────────────────────

class TestRoleConstants:
    def test_hierarchy_has_eight_roles(self):
        assert len(ALL_ROLES) == 8

    def test_admin_is_highest(self):
        assert ALL_ROLES[0] == ROLE_ADMIN

    def test_officer_is_lowest(self):
        assert ALL_ROLES[-1] == ROLE_OFFICER

    def test_hierarchy_order(self):
        expected = [
            ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II,
            ROLE_RD_HEAD, ROLE_GROUP_HEAD, ROLE_TEAM_LEADER, ROLE_OFFICER,
        ]
        assert ALL_ROLES == expected

    def test_all_roles_have_permissions(self):
        for role in ALL_ROLES:
            assert role in ROLE_PERMISSIONS

    def test_admin_has_manage_users(self):
        assert "manage_users" in ROLE_PERMISSIONS[ROLE_ADMIN]

    def test_officer_has_register_assignment(self):
        assert "register_assignment" in ROLE_PERMISSIONS[ROLE_OFFICER]

    def test_rd_head_has_approve_assignment(self):
        assert "approve_assignment" in ROLE_PERMISSIONS[ROLE_RD_HEAD]

    def test_team_leader_has_fill_details(self):
        assert "fill_assignment_details" in ROLE_PERMISSIONS[ROLE_TEAM_LEADER]

    def test_officer_cannot_manage_users(self):
        assert "manage_users" not in ROLE_PERMISSIONS[ROLE_OFFICER]

    def test_tl_cannot_approve_assignment(self):
        assert "approve_assignment" not in ROLE_PERMISSIONS[ROLE_TEAM_LEADER]


# ── is_admin (needs DB mock since get_user_role calls DB) ────────────

class TestIsAdmin:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_admin_user(self):
        assert is_admin(ADMIN_USER) is True

    def test_officer_user(self):
        assert is_admin(OFFICER_USER) is False

    def test_dg_user(self):
        assert is_admin(DG_USER) is False

    def test_rd_head_user(self):
        assert is_admin(RD_HEAD_USER) is False

    def test_admin_role_id_field(self):
        user = make_user(admin_role_id="ADMIN", role="OFFICER")
        assert is_admin(user) is True

    def test_empty_dict(self):
        assert is_admin({}) is False

    def test_none_role(self):
        user = make_user(role=None, admin_role_id=None)
        assert is_admin(user) is False


class TestIsHead:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_rd_head(self):
        assert is_head(RD_HEAD_USER) is True

    def test_group_head(self):
        assert is_head(GROUP_HEAD_USER) is True

    def test_admin_is_not_head(self):
        assert is_head(ADMIN_USER) is False

    def test_officer_is_not_head(self):
        assert is_head(OFFICER_USER) is False

    def test_tl_is_not_head(self):
        assert is_head(TL_USER) is False

    def test_dg_is_not_head(self):
        assert is_head(DG_USER) is False


class TestIsSeniorManagement:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_dg(self):
        assert is_senior_management(DG_USER) is True

    def test_ddg(self):
        assert is_senior_management(DDG_USER) is True

    def test_rd_head_is_not_senior(self):
        assert is_senior_management(RD_HEAD_USER) is False

    def test_officer_is_not_senior(self):
        assert is_senior_management(OFFICER_USER) is False

    def test_admin_is_not_senior_management(self):
        assert is_senior_management(ADMIN_USER) is False


class TestIsTeamLeader:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_tl_user(self):
        assert is_team_leader(TL_USER) is True

    def test_officer_is_not_tl(self):
        assert is_team_leader(OFFICER_USER) is False

    def test_admin_is_not_tl(self):
        assert is_team_leader(ADMIN_USER) is False

    def test_rd_head_is_not_tl(self):
        assert is_team_leader(RD_HEAD_USER) is False


class TestHasPermission:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_admin_has_manage_users(self):
        assert has_permission(ADMIN_USER, "manage_users") is True

    def test_officer_no_manage_users(self):
        assert has_permission(OFFICER_USER, "manage_users") is False

    def test_rd_head_has_approve_assignment(self):
        assert has_permission(RD_HEAD_USER, "approve_assignment") is True

    def test_tl_has_fill_details(self):
        assert has_permission(TL_USER, "fill_assignment_details") is True

    def test_officer_has_register(self):
        assert has_permission(OFFICER_USER, "register_assignment") is True

    def test_everyone_has_view_mis(self):
        for user in [ADMIN_USER, DG_USER, DDG_USER, RD_HEAD_USER, TL_USER, OFFICER_USER]:
            assert has_permission(user, "view_all_mis") is True

    def test_nonexistent_permission(self):
        assert has_permission(ADMIN_USER, "fly_to_moon") is False

    def test_empty_user(self):
        assert has_permission({}, "view_all_mis") is False


class TestPermissionCombinations:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_any_with_one_matching(self):
        assert has_any_permission(OFFICER_USER, ["manage_users", "register_assignment"]) is True

    def test_any_with_none_matching(self):
        assert has_any_permission(OFFICER_USER, ["manage_users", "import_data"]) is False

    def test_all_with_all_matching(self):
        assert has_all_permissions(ADMIN_USER, ["manage_users", "export_data"]) is True

    def test_all_with_one_missing(self):
        assert has_all_permissions(OFFICER_USER, ["view_all_mis", "manage_users"]) is False

    def test_any_empty_list(self):
        assert has_any_permission(OFFICER_USER, []) is False

    def test_all_empty_list(self):
        assert has_all_permissions(OFFICER_USER, []) is True


class TestGetRoleDisplayName:
    def test_admin(self):
        name = get_role_display_name(ROLE_ADMIN)
        assert isinstance(name, str)
        assert len(name) > 0

    def test_officer(self):
        name = get_role_display_name(ROLE_OFFICER)
        assert isinstance(name, str)

    def test_unknown_role(self):
        name = get_role_display_name("UNKNOWN_ROLE")
        assert isinstance(name, str)


class TestGetUserPermissions:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_admin_permissions_complete(self):
        perms = get_user_permissions(ADMIN_USER)
        assert "manage_users" in perms
        assert "export_data" in perms

    def test_officer_permissions_limited(self):
        perms = get_user_permissions(OFFICER_USER)
        assert "register_assignment" in perms
        assert "manage_users" not in perms

    def test_empty_user(self):
        perms = get_user_permissions({})
        assert isinstance(perms, list)


class TestCanApproveInOffice:
    def setup_method(self):
        self._patch = _mock_db()

    def teardown_method(self):
        self._patch.stop()

    def test_admin_can_approve_anywhere(self):
        assert can_approve_in_office(ADMIN_USER, "RDDEL") is True
        assert can_approve_in_office(ADMIN_USER, "HQ") is True

    def test_dg_can_approve_anywhere(self):
        assert can_approve_in_office(DG_USER, "RDDEL") is True

    def test_officer_cannot_approve(self):
        assert can_approve_in_office(OFFICER_USER, "HQ") is False

    def test_tl_cannot_approve(self):
        assert can_approve_in_office(TL_USER, "HQ") is False
