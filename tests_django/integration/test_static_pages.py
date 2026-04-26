"""
F.6 — static legal/informational pages tests (M0-CMS-06, COMP-09, COMP-12).
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestStaticPages:
    @pytest.mark.parametrize("path,marker", [
        ("/privacy/", b"Privacy Policy"),
        ("/terms/", b"Terms of Use"),
        ("/about/", b"About the PMS Portal"),
        ("/dpdp-notice/", b"Notice of Purpose"),
    ])
    def test_pages_render_unauthenticated(self, path, marker):
        r = TestClient().get(path)
        assert r.status_code == 200
        assert marker in r.content

    @pytest.mark.parametrize("path", ["/privacy/", "/terms/", "/about/", "/dpdp-notice/"])
    def test_pages_cross_link(self, path):
        r = TestClient().get(path)
        # Each legal page should link to the others (consistent footer)
        assert b"Privacy Policy" in r.content or b"privacy" in r.content
        assert b"Terms of Use" in r.content or b"terms" in r.content

    def test_dpdp_notice_cites_legal_basis(self):
        r = TestClient().get("/dpdp-notice/")
        # Required content for DPDP Section 5 notice
        assert b"DPDP" in r.content
        assert b"Section" in r.content
        assert b"Retention" in r.content
        assert b"7(b)" in r.content  # legal basis citation
