"""
Unit tests for report helper functions from app/routes/report_routes.py.

Tests _traffic_light color thresholds and _date_diff_sql for SQLite vs Postgres.
"""
import os
import sys
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.routes.report_routes import _traffic_light, _date_diff_sql

pytestmark = pytest.mark.unit


# ── _traffic_light ────────────────────────────────────────────────

class TestTrafficLight:
    """Traffic light: < 30 days → green, 30-59 → amber, >= 60 → red."""

    def test_0_days_green(self):
        assert _traffic_light(0) == 'green'

    def test_1_day_green(self):
        assert _traffic_light(1) == 'green'

    def test_15_days_green(self):
        assert _traffic_light(15) == 'green'

    def test_29_days_green(self):
        assert _traffic_light(29) == 'green'

    def test_30_days_amber(self):
        assert _traffic_light(30) == 'amber'

    def test_45_days_amber(self):
        assert _traffic_light(45) == 'amber'

    def test_59_days_amber(self):
        assert _traffic_light(59) == 'amber'

    def test_60_days_red(self):
        assert _traffic_light(60) == 'red'

    def test_90_days_red(self):
        assert _traffic_light(90) == 'red'

    def test_365_days_red(self):
        assert _traffic_light(365) == 'red'

    def test_negative_days_green(self):
        assert _traffic_light(-5) == 'green'

    def test_boundary_exactly_30(self):
        assert _traffic_light(30) == 'amber'

    def test_boundary_exactly_60(self):
        assert _traffic_light(60) == 'red'


# ── _date_diff_sql ────────────────────────────────────────────────

class TestDateDiffSql:
    """Test SQL generation for date difference calculation."""

    def test_sqlite_format(self):
        """Default test env uses SQLite (USE_POSTGRES=False)."""
        result = _date_diff_sql('target_date')
        # SQLite should use julianday
        assert 'julianday' in result
        assert 'target_date' in result

    def test_contains_column_name(self):
        result = _date_diff_sql('approved_at')
        assert 'approved_at' in result

    def test_different_columns(self):
        result1 = _date_diff_sql('created_at')
        result2 = _date_diff_sql('updated_at')
        assert 'created_at' in result1
        assert 'updated_at' in result2
        assert result1 != result2

    def test_returns_string(self):
        result = _date_diff_sql('some_column')
        assert isinstance(result, str)
        assert len(result) > 0

    def test_sqlite_has_cast_integer(self):
        """SQLite date diff should cast to INTEGER."""
        result = _date_diff_sql('target_date')
        assert 'INTEGER' in result or 'integer' in result.lower()

    def test_postgres_format(self):
        """When USE_POSTGRES is True, should use CURRENT_DATE - column::date."""
        with patch('app.routes.report_routes.USE_POSTGRES', True):
            result = _date_diff_sql('target_date')
            assert 'CURRENT_DATE' in result
            assert '::date' in result
            assert 'target_date' in result

    def test_postgres_no_julianday(self):
        """PostgreSQL format should not use julianday."""
        with patch('app.routes.report_routes.USE_POSTGRES', True):
            result = _date_diff_sql('target_date')
            assert 'julianday' not in result

    def test_sqlite_no_current_date_minus(self):
        """SQLite format should not use CURRENT_DATE - syntax."""
        with patch('app.routes.report_routes.USE_POSTGRES', False):
            result = _date_diff_sql('target_date')
            # SQLite uses julianday('now') - julianday(col), not CURRENT_DATE - col
            assert 'julianday' in result
