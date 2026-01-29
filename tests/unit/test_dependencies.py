"""
Unit tests for app/dependencies.py -- auth guards and permission wrappers.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.dependencies import (
    get_current_user,
    require_auth,
    is_admin,
    is_head,
    is_senior_management,
    is_team_leader,
    has_permission,
    require_admin,
    require_permission,
    require_head_or_above,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from __mocks__.fixtures import ADMIN_USER, OFFICER_USER, RD_HEAD_USER, TL_USER

pytestmark = pytest.mark.unit


def _make_request(cookie_value=None):
    """Create a mock Request object with optional session cookie."""
    request = MagicMock()
    if cookie_value:
        request.cookies = {"pms_session": cookie_value}
    else:
        request.cookies = {}
    return request


# ── get_current_user ─────────────────────────────────────────────────

class TestGetCurrentUser:
    def test_no_cookie_returns_none(self):
        request = _make_request(cookie_value=None)
        result = get_current_user(request)
        assert result is None

    @patch("app.dependencies.validate_session")
    @patch("app.dependencies.deserialize_session")
    def test_valid_cookie_returns_user(self, mock_deser, mock_validate):
        mock_deser.return_value = "session-123"
        mock_validate.return_value = OFFICER_USER

        request = _make_request(cookie_value="valid-token")
        result = get_current_user(request)
        assert result == OFFICER_USER

    @patch("app.dependencies.validate_session")
    @patch("app.dependencies.deserialize_session")
    def test_invalid_token_returns_none(self, mock_deser, mock_validate):
        mock_deser.return_value = None
        request = _make_request(cookie_value="bad-token")
        result = get_current_user(request)
        assert result is None

    @patch("app.dependencies.validate_session")
    @patch("app.dependencies.deserialize_session")
    def test_expired_session_returns_none(self, mock_deser, mock_validate):
        mock_deser.return_value = "session-123"
        mock_validate.return_value = None  # expired

        request = _make_request(cookie_value="valid-token")
        result = get_current_user(request)
        assert result is None


# ── require_auth ─────────────────────────────────────────────────────

class TestRequireAuth:
    @patch("app.dependencies.get_current_user")
    def test_authenticated_returns_user(self, mock_get_user):
        mock_get_user.return_value = OFFICER_USER
        request = _make_request()
        result = require_auth(request)
        assert result == OFFICER_USER

    @patch("app.dependencies.get_current_user")
    def test_unauthenticated_raises_401(self, mock_get_user):
        from fastapi import HTTPException
        mock_get_user.return_value = None
        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            require_auth(request)
        assert exc_info.value.status_code == 401


# ── Wrapper functions ────────────────────────────────────────────────

class TestRoleWrappers:
    def setup_method(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        self._patch = patch("app.database.get_db")
        m = self._patch.start()
        m.return_value.__enter__ = MagicMock(return_value=mock_conn)
        m.return_value.__exit__ = MagicMock(return_value=False)

    def teardown_method(self):
        self._patch.stop()

    def test_is_admin_wraps_correctly(self):
        assert is_admin(ADMIN_USER) is True
        assert is_admin(OFFICER_USER) is False

    def test_is_head_wraps_correctly(self):
        assert is_head(RD_HEAD_USER) is True
        assert is_head(OFFICER_USER) is False

    def test_is_team_leader_wraps_correctly(self):
        assert is_team_leader(TL_USER) is True
        assert is_team_leader(OFFICER_USER) is False

    def test_has_permission_wraps_correctly(self):
        assert has_permission(ADMIN_USER, "manage_users") is True
        assert has_permission(OFFICER_USER, "manage_users") is False


# ── require_admin ────────────────────────────────────────────────────

class TestRequireAdmin:
    def setup_method(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        self._db_patch = patch("app.database.get_db")
        m = self._db_patch.start()
        m.return_value.__enter__ = MagicMock(return_value=mock_conn)
        m.return_value.__exit__ = MagicMock(return_value=False)

    def teardown_method(self):
        self._db_patch.stop()

    @patch("app.dependencies.get_current_user")
    def test_admin_returns_user(self, mock_get_user):
        mock_get_user.return_value = ADMIN_USER
        request = _make_request()
        result = require_admin(request)
        assert result == ADMIN_USER

    @patch("app.dependencies.get_current_user")
    def test_non_admin_returns_none(self, mock_get_user):
        mock_get_user.return_value = OFFICER_USER
        request = _make_request()
        result = require_admin(request)
        assert result is None

    @patch("app.dependencies.get_current_user")
    def test_unauthenticated_returns_none(self, mock_get_user):
        mock_get_user.return_value = None
        request = _make_request()
        result = require_admin(request)
        assert result is None


# ── require_permission ───────────────────────────────────────────────

class TestRequirePermission:
    def setup_method(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        self._db_patch = patch("app.database.get_db")
        m = self._db_patch.start()
        m.return_value.__enter__ = MagicMock(return_value=mock_conn)
        m.return_value.__exit__ = MagicMock(return_value=False)

    def teardown_method(self):
        self._db_patch.stop()

    @patch("app.dependencies.get_current_user")
    def test_user_with_permission(self, mock_get_user):
        mock_get_user.return_value = ADMIN_USER
        request = _make_request()
        user, redirect = require_permission(request, "manage_users")
        assert user == ADMIN_USER
        assert redirect is None

    @patch("app.dependencies.get_current_user")
    def test_user_without_permission(self, mock_get_user):
        mock_get_user.return_value = OFFICER_USER
        request = _make_request()
        user, redirect = require_permission(request, "manage_users")
        assert user is None
        assert redirect is not None
        assert redirect.status_code == 302

    @patch("app.dependencies.get_current_user")
    def test_unauthenticated_redirects_to_login(self, mock_get_user):
        mock_get_user.return_value = None
        request = _make_request()
        user, redirect = require_permission(request, "manage_users")
        assert user is None
        assert redirect is not None


# ── require_head_or_above ────────────────────────────────────────────

class TestRequireHeadOrAbove:
    def setup_method(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        self._db_patch = patch("app.database.get_db")
        m = self._db_patch.start()
        m.return_value.__enter__ = MagicMock(return_value=mock_conn)
        m.return_value.__exit__ = MagicMock(return_value=False)

    def teardown_method(self):
        self._db_patch.stop()

    @patch("app.dependencies.get_current_user")
    def test_rd_head_allowed(self, mock_get_user):
        mock_get_user.return_value = RD_HEAD_USER
        request = _make_request()
        user, redirect = require_head_or_above(request)
        assert user == RD_HEAD_USER
        assert redirect is None

    @patch("app.dependencies.get_current_user")
    def test_admin_allowed(self, mock_get_user):
        mock_get_user.return_value = ADMIN_USER
        request = _make_request()
        user, redirect = require_head_or_above(request)
        assert user is not None
        assert redirect is None

    @patch("app.dependencies.get_current_user")
    def test_officer_denied(self, mock_get_user):
        mock_get_user.return_value = OFFICER_USER
        request = _make_request()
        user, redirect = require_head_or_above(request)
        assert user is None
        assert redirect is not None

    @patch("app.dependencies.get_current_user")
    def test_tl_denied(self, mock_get_user):
        mock_get_user.return_value = TL_USER
        request = _make_request()
        user, redirect = require_head_or_above(request)
        assert user is None
        assert redirect is not None
