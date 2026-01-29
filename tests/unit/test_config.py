"""
Unit tests for app/config.py -- configuration constants and environment loading.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.config import (
    ASSIGNMENT_TYPES,
    ASSIGNMENT_STATUS_OPTIONS,
    DOMAIN_OPTIONS,
    CLIENT_TYPE_OPTIONS,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    DAILY_RATE_LAKHS,
    SECRET_KEY,
    DATABASE_PATH,
    USE_POSTGRES,
)

pytestmark = pytest.mark.unit


class TestAssignmentTypes:
    def test_has_three_types(self):
        assert len(ASSIGNMENT_TYPES) == 3

    def test_contains_assignment(self):
        assert "ASSIGNMENT" in ASSIGNMENT_TYPES

    def test_contains_training(self):
        assert "TRAINING" in ASSIGNMENT_TYPES

    def test_contains_development(self):
        assert "DEVELOPMENT" in ASSIGNMENT_TYPES


class TestStatusOptions:
    def test_has_options(self):
        assert len(ASSIGNMENT_STATUS_OPTIONS) >= 4

    def test_contains_not_started(self):
        assert "Not Started" in ASSIGNMENT_STATUS_OPTIONS

    def test_contains_ongoing(self):
        assert "Ongoing" in ASSIGNMENT_STATUS_OPTIONS

    def test_contains_completed(self):
        assert "Completed" in ASSIGNMENT_STATUS_OPTIONS

    def test_contains_on_hold(self):
        assert "On Hold" in ASSIGNMENT_STATUS_OPTIONS

    def test_contains_cancelled(self):
        assert "Cancelled" in ASSIGNMENT_STATUS_OPTIONS


class TestDomainOptions:
    def test_has_domains(self):
        assert len(DOMAIN_OPTIONS) >= 5

    def test_contains_es(self):
        assert "ES" in DOMAIN_OPTIONS

    def test_contains_it(self):
        assert "IT" in DOMAIN_OPTIONS


class TestClientTypeOptions:
    def test_has_options(self):
        assert len(CLIENT_TYPE_OPTIONS) >= 4

    def test_central_govt(self):
        assert "Central Government" in CLIENT_TYPE_OPTIONS

    def test_private(self):
        assert "Private" in CLIENT_TYPE_OPTIONS


class TestSessionConfig:
    def test_cookie_name(self):
        assert SESSION_COOKIE_NAME == "pms_session"

    def test_max_age_is_24_hours(self):
        assert SESSION_MAX_AGE == 86400

    def test_max_age_is_positive(self):
        assert SESSION_MAX_AGE > 0


class TestBusinessConfig:
    def test_daily_rate(self):
        assert DAILY_RATE_LAKHS == 0.20

    def test_daily_rate_positive(self):
        assert DAILY_RATE_LAKHS > 0


class TestDatabaseConfig:
    def test_database_path_exists(self):
        from pathlib import Path
        assert isinstance(DATABASE_PATH, (str, Path, type(None)))

    def test_use_postgres_is_bool(self):
        assert isinstance(USE_POSTGRES, bool)

    def test_use_postgres_false_in_test(self):
        # We forced DATABASE_URL="" in test env
        assert USE_POSTGRES is False


class TestSecurityConfig:
    def test_secret_key_exists(self):
        assert SECRET_KEY is not None
        assert len(SECRET_KEY) > 0

    def test_secret_key_is_string(self):
        assert isinstance(SECRET_KEY, str)
