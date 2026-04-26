"""
F.12 — probe_hosting tests (M0-OPS-15).
"""
from io import StringIO

import pytest
from django.core.management import call_command


pytestmark = pytest.mark.django_db


class TestProbeHosting:
    def test_runs_and_emits_summary(self, db):
        out = StringIO()
        call_command("probe_hosting", stdout=out)
        text = out.getvalue()
        # Header + sections we expect
        assert "PMS Hosting Capability Probe" in text
        assert "Python" in text
        assert "Django" in text
        assert "DB SELECT 1" in text
        assert "MEDIA_ROOT writable" in text
        assert "EMAIL_BACKEND" in text
        # Final tally
        assert "OK," in text
        assert "failed" in text

    def test_reports_dependent_packages(self, db):
        out = StringIO()
        call_command("probe_hosting", stdout=out)
        text = out.getvalue()
        for pkg in ("axes", "auditlog", "django_fsm", "whitenoise", "openpyxl", "pymysql"):
            assert pkg in text


class TestLanguageCodeIsIndianEnglish:
    """M0-L10N-04 — locale set to en-in for DD/MM/YYYY default formatting."""
    def test_settings_language_code(self, settings):
        assert settings.LANGUAGE_CODE == "en-in"
