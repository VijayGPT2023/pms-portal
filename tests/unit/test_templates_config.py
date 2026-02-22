"""
Unit tests for app/templates_config.py -- date formatting, JSON serialization.
"""
import os
import sys
import json
import pytest
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.templates_config import format_date, format_datetime, safe_tojson, json_serial, lakh_format, pct_format

pytestmark = pytest.mark.unit


# ── format_date ──────────────────────────────────────────────────────

class TestFormatDate:
    def test_none_returns_dash(self):
        assert format_date(None) == "-"

    def test_datetime_object(self):
        dt = datetime(2025, 3, 15, 10, 30, 45)
        result = format_date(dt)
        assert result == "2025-03-15"

    def test_date_string(self):
        result = format_date("2025-03-15")
        assert result == "2025-03-15"

    def test_datetime_string(self):
        result = format_date("2025-03-15 10:30:45")
        assert result == "2025-03-15"

    def test_empty_string(self):
        result = format_date("")
        assert isinstance(result, str)

    def test_date_object(self):
        d = date(2025, 6, 1)
        result = format_date(d)
        assert "2025-06-01" in result


# ── format_datetime ──────────────────────────────────────────────────

class TestFormatDatetime:
    def test_none_returns_dash(self):
        assert format_datetime(None) == "-"

    def test_datetime_object(self):
        dt = datetime(2025, 3, 15, 10, 30, 45)
        result = format_datetime(dt)
        assert "2025-03-15" in result
        assert "10:30:45" in result

    def test_string_input(self):
        result = format_datetime("2025-03-15 10:30:45")
        assert "2025-03-15" in result

    def test_empty_string(self):
        result = format_datetime("")
        assert isinstance(result, str)


# ── json_serial ──────────────────────────────────────────────────────

class TestJsonSerial:
    def test_datetime_serialized(self):
        dt = datetime(2025, 3, 15, 10, 30, 45)
        result = json_serial(dt)
        assert "2025-03-15" in result

    def test_date_not_handled(self):
        """json_serial only handles datetime, not date."""
        d = date(2025, 3, 15)
        with pytest.raises(TypeError):
            json_serial(d)

    def test_non_datetime_raises(self):
        with pytest.raises(TypeError):
            json_serial("not-a-datetime")

    def test_int_raises(self):
        with pytest.raises(TypeError):
            json_serial(42)


# ── safe_tojson ──────────────────────────────────────────────────────

class TestSafeTojson:
    def test_dict(self):
        result = safe_tojson({"key": "value"})
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_list(self):
        result = safe_tojson([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_dict_with_datetime(self):
        data = {"ts": datetime(2025, 1, 1)}
        result = safe_tojson(data)
        parsed = json.loads(result)
        assert "2025-01-01" in parsed["ts"]

    def test_none(self):
        result = safe_tojson(None)
        assert result == "null"

    def test_string(self):
        result = safe_tojson("hello")
        assert json.loads(result) == "hello"

    def test_number(self):
        result = safe_tojson(42)
        assert json.loads(result) == 42

    def test_nested_dict(self):
        data = {"a": {"b": [1, 2]}}
        result = safe_tojson(data)
        parsed = json.loads(result)
        assert parsed["a"]["b"] == [1, 2]


# ── lakh_format ──────────────────────────────────────────────────────

class TestLakhFormat:
    def test_none_returns_dash(self):
        assert lakh_format(None) == "-"

    def test_zero(self):
        assert lakh_format(0) == "0.00L"

    def test_one_lakh(self):
        assert lakh_format(100000) == "1.00L"

    def test_large_number(self):
        result = lakh_format(1234567)
        assert "12.35" in result
        assert "L" in result

    def test_without_symbol(self):
        result = lakh_format(100000, symbol=False)
        assert "L" not in result
        assert "1.00" in result

    def test_negative_value(self):
        result = lakh_format(-500000)
        assert "-5.00" in result
        assert "L" in result

    def test_string_number(self):
        result = lakh_format("200000")
        assert "2.00L" in result

    def test_invalid_string(self):
        assert lakh_format("not-a-number") == "not-a-number"

    def test_decimal_value(self):
        result = lakh_format(50000.5)
        assert "0.50L" in result


# ── pct_format ───────────────────────────────────────────────────────

class TestPctFormat:
    def test_none_returns_dash(self):
        assert pct_format(None) == "-"

    def test_whole_number(self):
        assert pct_format(85) == "85.0%"

    def test_decimal(self):
        assert pct_format(75.6) == "75.6%"

    def test_zero(self):
        assert pct_format(0) == "0.0%"

    def test_custom_decimals(self):
        assert pct_format(85.678, decimals=2) == "85.68%"

    def test_string_number(self):
        assert pct_format("92.5") == "92.5%"

    def test_invalid_string(self):
        assert pct_format("abc") == "abc"
