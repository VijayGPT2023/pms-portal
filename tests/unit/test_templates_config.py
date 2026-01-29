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

from app.templates_config import format_date, format_datetime, safe_tojson, json_serial

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
