"""
Unit tests for new database functions added in Phase 2 --
generate_utilization_claim_number, generate_client_code, and verification
that new tables exist in the schema (clients, assignment_clients,
utilization_claims, finance_officers, proposal_documents, invoice_milestone_links).
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.database import (
    generate_utilization_claim_number,
    generate_client_code,
    init_database,
)

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


# ── generate_utilization_claim_number ─────────────────────────────

class TestGenerateUtilizationClaimNumber:
    def setup_method(self):
        self._patch, self._cursor = _mock_db(next_num=1)

    def teardown_method(self):
        self._patch.stop()

    def test_format_pattern(self):
        import re
        result = generate_utilization_claim_number("OFF001", "2025-06")
        pattern = r'^UTL/OFF001/2025-06/\d{4}$'
        assert re.match(pattern, result), f"{result} does not match expected format"

    def test_first_claim_is_0001(self):
        result = generate_utilization_claim_number("OFF001", "2025-06")
        assert result == "UTL/OFF001/2025-06/0001"

    def test_includes_officer_id(self):
        result = generate_utilization_claim_number("TL002", "2025-07")
        assert "TL002" in result

    def test_includes_claim_month(self):
        result = generate_utilization_claim_number("OFF001", "2025-12")
        assert "2025-12" in result

    def test_starts_with_utl(self):
        result = generate_utilization_claim_number("OFF001", "2025-01")
        assert result.startswith("UTL/")

    def test_four_digit_sequence(self):
        result = generate_utilization_claim_number("OFF001", "2025-01")
        seq = result.split("/")[-1]
        assert len(seq) == 4
        assert seq.isdigit()

    def test_second_claim_number(self):
        self._patch.stop()
        self._patch, self._cursor = _mock_db(next_num=2)
        result = generate_utilization_claim_number("OFF001", "2025-06")
        assert result.endswith("/0002")

    def test_large_sequence(self):
        self._patch.stop()
        self._patch, self._cursor = _mock_db(next_num=99)
        result = generate_utilization_claim_number("OFF001", "2025-06")
        assert result.endswith("/0099")

    def test_queries_with_like_pattern(self):
        generate_utilization_claim_number("OFF001", "2025-06")
        call_args = self._cursor.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "LIKE" in query
        assert "UTL/OFF001/2025-06/" in params[0]


# ── generate_client_code ──────────────────────────────────────────

class TestGenerateClientCode:
    def setup_method(self):
        self._patch, self._cursor = _mock_db(next_num=1)

    def teardown_method(self):
        self._patch.stop()

    def test_format_pattern(self):
        import re
        result = generate_client_code("Test Corp", "Central Government")
        pattern = r'^CLT/[A-Z]+/\d{4}$'
        assert re.match(pattern, result), f"{result} does not match CLT/PREFIX/NNNN"

    def test_central_govt_code(self):
        result = generate_client_code("Ministry of X", "Central Government")
        assert result == "CLT/CG/0001"

    def test_psu_code(self):
        result = generate_client_code("NTPC", "PSU")
        assert result == "CLT/PSU/0001"

    def test_private_code(self):
        result = generate_client_code("TCS", "Private")
        assert result == "CLT/PVT/0001"

    def test_queries_with_like_pattern(self):
        generate_client_code("Test", "PSU")
        call_args = self._cursor.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "LIKE" in query
        assert "CLT/PSU/" in params[0]


# ── Schema verification ──────────────────────────────────────────

class TestNewTablesInSchema:
    """Verify that init_database creates the new Phase 2 tables by
    inspecting the SQL statements passed to cursor.execute."""

    def test_clients_table_created(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            # Collect all SQL statements
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0]
            ).upper()
            assert "CREATE TABLE IF NOT EXISTS CLIENTS" in all_sql
        finally:
            _patch.stop()

    def test_assignment_clients_table_created(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0]
            ).upper()
            assert "CREATE TABLE IF NOT EXISTS ASSIGNMENT_CLIENTS" in all_sql
        finally:
            _patch.stop()

    def test_utilization_claims_table_created(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0]
            ).upper()
            assert "CREATE TABLE IF NOT EXISTS UTILIZATION_CLAIMS" in all_sql
        finally:
            _patch.stop()

    def test_finance_officers_table_created(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0]
            ).upper()
            assert "CREATE TABLE IF NOT EXISTS FINANCE_OFFICERS" in all_sql
        finally:
            _patch.stop()

    def test_proposal_documents_table_created(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0]
            ).upper()
            assert "CREATE TABLE IF NOT EXISTS PROPOSAL_DOCUMENTS" in all_sql
        finally:
            _patch.stop()

    def test_invoice_milestone_links_table_created(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0]
            ).upper()
            assert "CREATE TABLE IF NOT EXISTS INVOICE_MILESTONE_LINKS" in all_sql
        finally:
            _patch.stop()

    def test_clients_table_has_client_code_column(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0] and "CLIENTS" in str(call[0][0]).upper()
                and "CREATE" in str(call[0][0]).upper()
            ).upper()
            assert "CLIENT_CODE" in all_sql
        finally:
            _patch.stop()

    def test_utilization_claims_has_claim_type_column(self):
        _patch, cursor = _mock_db()
        try:
            init_database()
            all_sql = " ".join(
                str(call[0][0]) for call in cursor.execute.call_args_list
                if call[0] and "UTILIZATION_CLAIMS" in str(call[0][0]).upper()
                and "CREATE" in str(call[0][0]).upper()
            ).upper()
            assert "CLAIM_TYPE" in all_sql
        finally:
            _patch.stop()
