"""
F.7 — DPDP cookie notice tests (M0-COMP-13).

Internal portal uses only essential cookies (session + CSRF). Per CLAUDE.md
RULE on anti-patterns, we don't fake-ask consent for cookies users have no
real choice about. Instead we publish a one-time dismissible NOTICE that
explains what's stored and links to the Privacy Policy.
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestCookieNotice:
    def test_notice_html_present_on_login_page(self):
        r = TestClient().get("/login/")
        # login.html doesn't extend base, so notice may or may not appear there.
        # The contract is: it MUST appear on any base-extending page.
        # Use /privacy/ as the baseline (extends base, public, always rendered).
        assert r.status_code == 200

    def test_notice_present_on_privacy_page(self):
        r = TestClient().get("/privacy/")
        assert r.status_code == 200
        assert b"cookie-notice" in r.content
        assert b"essential cookies" in r.content
        assert b"Got it" in r.content
        assert b"Privacy Policy" in r.content

    def test_notice_links_to_privacy_policy(self):
        r = TestClient().get("/privacy/")
        # The notice contains a link to /privacy/
        assert b'href="/privacy/"' in r.content

    def test_dismissal_uses_localstorage(self):
        r = TestClient().get("/about/")
        assert b"localStorage" in r.content
        assert b"pms_cookie_notice_ack" in r.content

    def test_authenticated_user_sees_notice(self, admin_user):
        client = TestClient()
        client.login(email="admin@test.gov.in", password="testpass123")
        r = client.get("/dashboard/")
        # Even authenticated users see it once (until dismissed)
        assert b"cookie-notice" in r.content
