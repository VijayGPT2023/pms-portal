"""
F.8 — security headers tests (M0-SEC-03, SEC-04).
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestSecurityHeaders:
    """All routes (public + authenticated) must carry the headers."""

    @pytest.mark.parametrize("path", ["/login/", "/privacy/", "/health/"])
    def test_csp_report_only_default(self, path):
        r = TestClient().get(path)
        # Default mode: Report-Only header set, enforce header absent
        assert "Content-Security-Policy-Report-Only" in r
        assert "Content-Security-Policy" not in r
        csp = r["Content-Security-Policy-Report-Only"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

    def test_csp_enforce_when_setting_on(self, settings):
        settings.CSP_ENFORCE = True
        r = TestClient().get("/login/")
        assert "Content-Security-Policy" in r
        assert "Content-Security-Policy-Report-Only" not in r

    def test_permissions_policy_present(self):
        r = TestClient().get("/login/")
        pp = r["Permissions-Policy"]
        # Locked-down by default
        for feature in ("camera=()", "microphone=()", "geolocation=()", "payment=()"):
            assert feature in pp

    def test_referrer_policy_present(self):
        r = TestClient().get("/login/")
        # Either set by SecurityMiddleware (SECURE_REFERRER_POLICY) or our middleware
        assert "Referrer-Policy" in r
        assert "strict-origin" in r["Referrer-Policy"]

    def test_x_content_type_options_present(self):
        # Django's SecurityMiddleware via SECURE_CONTENT_TYPE_NOSNIFF
        r = TestClient().get("/login/")
        assert r["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options_present(self):
        # Django's XFrameOptionsMiddleware (default: SAMEORIGIN/DENY)
        r = TestClient().get("/login/")
        assert "X-Frame-Options" in r

    def test_authenticated_pages_also_carry_headers(self, admin_user):
        client = TestClient()
        client.login(email="admin@test.gov.in", password="testpass123")
        r = client.get("/dashboard/")
        assert "Content-Security-Policy-Report-Only" in r
        assert "Permissions-Policy" in r
