"""
Unit tests for app/auth.py -- password hashing, session management, authentication.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.auth import (
    generate_password,
    hash_password,
    verify_password,
    generate_session_id,
    create_session,
    validate_session,
    delete_session,
    update_session_role,
    authenticate_officer,
    serialize_session,
    deserialize_session,
    get_serializer,
)

pytestmark = pytest.mark.unit


# ── generate_password ────────────────────────────────────────────────

class TestGeneratePassword:
    def test_default_length(self):
        pwd = generate_password()
        assert len(pwd) == 12

    def test_custom_length(self):
        pwd = generate_password(length=20)
        assert len(pwd) == 20

    def test_min_length(self):
        pwd = generate_password(length=1)
        assert len(pwd) == 1

    def test_uniqueness(self):
        passwords = {generate_password() for _ in range(100)}
        assert len(passwords) == 100  # all unique

    def test_contains_valid_chars(self):
        import string
        valid = set(string.ascii_letters + string.digits + "!@#$%^&*")
        pwd = generate_password(length=100)
        for ch in pwd:
            assert ch in valid


# ── hash_password / verify_password ──────────────────────────────────

class TestPasswordHashing:
    def test_hash_returns_string(self):
        h = hash_password("hello")
        assert isinstance(h, str)

    def test_hash_not_plaintext(self):
        h = hash_password("secret123")
        assert h != "secret123"

    def test_verify_correct_password(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("mypassword")
        assert verify_password("wrongpassword", h) is False

    def test_verify_empty_password_against_hash(self):
        h = hash_password("notempty")
        assert verify_password("", h) is False

    def test_hash_empty_password(self):
        h = hash_password("")
        assert verify_password("", h) is True

    def test_verify_malformed_hash(self):
        assert verify_password("anything", "not-a-valid-hash") is False

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_same_password_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        # bcrypt uses random salt, so hashes differ
        assert h1 != h2
        # But both verify
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_unicode_password(self):
        h = hash_password("p\u00e4ssw\u00f6rd")
        assert verify_password("p\u00e4ssw\u00f6rd", h) is True

    def test_long_password_raises(self):
        """bcrypt rejects passwords longer than 72 bytes."""
        long_pwd = "a" * 200
        with pytest.raises(ValueError):
            hash_password(long_pwd)

    def test_special_characters_password(self):
        pwd = "P@$$w0rd!#%^&*()"
        h = hash_password(pwd)
        assert verify_password(pwd, h) is True


# ── generate_session_id ──────────────────────────────────────────────

class TestGenerateSessionId:
    def test_returns_string(self):
        sid = generate_session_id()
        assert isinstance(sid, str)

    def test_length_reasonable(self):
        sid = generate_session_id()
        assert len(sid) > 20

    def test_uniqueness(self):
        ids = {generate_session_id() for _ in range(100)}
        assert len(ids) == 100

    def test_url_safe(self):
        sid = generate_session_id()
        # Should be URL-safe base64
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', sid)


# ── serialize / deserialize session ──────────────────────────────────

class TestSessionSerialization:
    def test_roundtrip(self):
        sid = "test-session-id-12345"
        token = serialize_session(sid)
        result = deserialize_session(token)
        assert result == sid

    def test_tampered_token_returns_none(self):
        token = serialize_session("real-session")
        result = deserialize_session(token + "tampered")
        assert result is None

    def test_empty_token_returns_none(self):
        result = deserialize_session("")
        assert result is None

    def test_garbage_token_returns_none(self):
        result = deserialize_session("not-a-valid-token-at-all")
        assert result is None

    def test_serializer_uses_secret_key(self):
        s = get_serializer()
        assert s is not None


# ── create_session (mocked DB) ───────────────────────────────────────

class TestCreateSession:
    @patch("app.auth.get_db")
    def test_creates_session_returns_id(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        sid = create_session("OFF001", "OFFICER")
        assert isinstance(sid, str)
        assert len(sid) > 0

        # Should delete old sessions and insert new one
        calls = mock_cursor.execute.call_args_list
        assert len(calls) >= 2  # DELETE + INSERT

    @patch("app.auth.get_db")
    def test_deletes_existing_sessions(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        create_session("OFF001")
        first_call_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "DELETE" in first_call_sql.upper()


# ── validate_session (mocked DB) ─────────────────────────────────────

class TestValidateSession:
    @patch("app.auth.get_db")
    def test_invalid_session_returns_none(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = validate_session("nonexistent-session")
        assert result is None

    @patch("app.auth.get_db")
    def test_expired_session_returns_none(self, mock_get_db):
        from datetime import datetime, timedelta

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Return an expired session
        expired_session = {
            "officer_id": "OFF001",
            "active_role": "OFFICER",
            "expires_at": datetime.now() - timedelta(hours=1),
        }
        mock_cursor.fetchone.side_effect = [expired_session]
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = validate_session("expired-session")
        assert result is None


# ── delete_session (mocked DB) ───────────────────────────────────────

class TestDeleteSession:
    @patch("app.auth.get_db")
    def test_deletes_session(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        delete_session("session-to-delete")
        call_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "DELETE" in call_sql.upper()
        assert "sessions" in call_sql.lower()


# ── update_session_role (mocked DB) ──────────────────────────────────

class TestUpdateSessionRole:
    @patch("app.auth.get_db")
    def test_update_role_returns_true(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = update_session_role("session-123", "RD_HEAD")
        assert result is True

    @patch("app.auth.get_db")
    def test_update_nonexistent_returns_false(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = update_session_role("nonexistent", "ADMIN")
        assert result is False


# ── authenticate_officer (mocked DB) ─────────────────────────────────

class TestAuthenticateOfficer:
    @patch("app.auth.get_db")
    def test_valid_credentials(self, mock_get_db):
        from app.auth import hash_password as hp

        pw_hash = hp("correct_password")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "officer_id": "OFF001",
            "name": "Test",
            "email": "test@npc.in",
            "office_id": "HQ",
            "designation": "Consultant",
            "password_hash": pw_hash,
            "is_active": 1,
        }
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = authenticate_officer("test@npc.in", "correct_password")
        assert result is not None
        assert result["officer_id"] == "OFF001"

    @patch("app.auth.get_db")
    def test_wrong_password(self, mock_get_db):
        from app.auth import hash_password as hp

        pw_hash = hp("correct_password")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "officer_id": "OFF001",
            "name": "Test",
            "email": "test@npc.in",
            "office_id": "HQ",
            "designation": "Consultant",
            "password_hash": pw_hash,
            "is_active": 1,
        }
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = authenticate_officer("test@npc.in", "wrong_password")
        assert result is None

    @patch("app.auth.get_db")
    def test_email_not_found(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = authenticate_officer("nobody@npc.in", "password")
        assert result is None

    @patch("app.auth.get_db")
    def test_inactive_officer(self, mock_get_db):
        from app.auth import hash_password as hp

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "officer_id": "OFF001",
            "name": "Test",
            "email": "test@npc.in",
            "office_id": "HQ",
            "designation": "Consultant",
            "password_hash": hp("password"),
            "is_active": 0,
        }
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = authenticate_officer("test@npc.in", "password")
        assert result is None
