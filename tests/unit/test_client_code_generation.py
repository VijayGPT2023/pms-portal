"""
Unit tests for client code and activity number generation from
app/database.py -- generate_client_code function.

Tests the CLT/TYPE_PREFIX/NNNN format and correct type prefix mapping.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.database import generate_client_code

pytestmark = pytest.mark.unit


def _mock_db(next_num=1):
    """Return a patch for app.database.get_db with configurable sequence number."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"next_num": next_num}
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    p = patch("app.database.get_db")
    m = p.start()
    m.return_value.__enter__ = MagicMock(return_value=mock_conn)
    m.return_value.__exit__ = MagicMock(return_value=False)
    return p, mock_cursor


# ── Client code format ────────────────────────────────────────────

class TestClientCodeFormat:
    def setup_method(self):
        self._patch, self._cursor = _mock_db(next_num=1)

    def teardown_method(self):
        self._patch.stop()

    def test_starts_with_clt_prefix(self):
        code = generate_client_code("Test Corp", "Central Government")
        assert code.startswith("CLT/")

    def test_format_three_parts(self):
        code = generate_client_code("Test Corp", "Central Government")
        parts = code.split("/")
        assert len(parts) == 3

    def test_sequence_is_four_digits(self):
        code = generate_client_code("Test Corp", "Private")
        parts = code.split("/")
        assert len(parts[2]) == 4
        assert parts[2].isdigit()

    def test_format_pattern(self):
        import re
        code = generate_client_code("ABC Corp", "PSU")
        pattern = r'^CLT/[A-Z]+/\d{4}$'
        assert re.match(pattern, code), f"Code {code} does not match CLT/PREFIX/NNNN"


# ── Type prefix mapping ──────────────────────────────────────────

class TestClientCodeTypePrefixes:
    def setup_method(self):
        self._patch, self._cursor = _mock_db(next_num=1)

    def teardown_method(self):
        self._patch.stop()

    def test_central_government_prefix(self):
        code = generate_client_code("Ministry of Finance", "Central Government")
        assert code == "CLT/CG/0001"

    def test_state_government_prefix(self):
        code = generate_client_code("Govt of Maharashtra", "State Government")
        assert code == "CLT/SG/0001"

    def test_psu_prefix(self):
        code = generate_client_code("BHEL", "PSU")
        assert code == "CLT/PSU/0001"

    def test_private_prefix(self):
        code = generate_client_code("Infosys Ltd", "Private")
        assert code == "CLT/PVT/0001"

    def test_international_prefix(self):
        code = generate_client_code("World Bank", "International")
        assert code == "CLT/INT/0001"

    def test_others_prefix(self):
        code = generate_client_code("Unknown Entity", "Others")
        assert code == "CLT/OTH/0001"

    def test_unknown_type_defaults_to_oth(self):
        code = generate_client_code("Some Client", "NonexistentType")
        assert code == "CLT/OTH/0001"


# ── Sequence numbers ──────────────────────────────────────────────

class TestClientCodeSequence:
    def test_first_client_gets_0001(self):
        patch_obj, cursor = _mock_db(next_num=1)
        try:
            code = generate_client_code("First Corp", "Private")
            assert code.endswith("/0001")
        finally:
            patch_obj.stop()

    def test_second_client_gets_0002(self):
        patch_obj, cursor = _mock_db(next_num=2)
        try:
            code = generate_client_code("Second Corp", "Private")
            assert code.endswith("/0002")
        finally:
            patch_obj.stop()

    def test_large_sequence_number(self):
        patch_obj, cursor = _mock_db(next_num=999)
        try:
            code = generate_client_code("Big Corp", "Private")
            assert code.endswith("/0999")
        finally:
            patch_obj.stop()

    def test_four_digit_sequence(self):
        patch_obj, cursor = _mock_db(next_num=1234)
        try:
            code = generate_client_code("Large Corp", "PSU")
            assert code.endswith("/1234")
        finally:
            patch_obj.stop()


# ── Different client names (should not affect code) ───────────────

class TestClientCodeNameIndependent:
    def setup_method(self):
        self._patch, self._cursor = _mock_db(next_num=5)

    def teardown_method(self):
        self._patch.stop()

    def test_short_name(self):
        code = generate_client_code("A", "PSU")
        assert code == "CLT/PSU/0005"

    def test_long_name(self):
        code = generate_client_code("Very Long Client Name Corporation Ltd", "PSU")
        assert code == "CLT/PSU/0005"

    def test_name_with_special_chars(self):
        code = generate_client_code("ABC & Assoc. (India)", "Private")
        assert code == "CLT/PVT/0005"
