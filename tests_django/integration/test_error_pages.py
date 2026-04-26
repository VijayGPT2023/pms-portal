"""
F.9 — custom 404 / 500 / 403 error page tests (M0-REL-11).

Django uses these templates automatically when:
  - 404: a view raises Http404 or no URL matches (DEBUG=False)
  - 500: an unhandled exception (DEBUG=False)
  - 403: a view raises PermissionDenied (DEBUG=False)

In tests DEBUG defaults to True, so we override per-test to exercise the
template-rendering path.
"""
import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db


class TestCustomErrorPages:
    def test_404_renders_branded_page(self, settings):
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = ["*"]
        r = TestClient(raise_request_exception=False).get("/no-such-route-anywhere/")
        assert r.status_code == 404
        assert b"Page not found" in r.content
        assert b"PMS Portal" in r.content
        assert b"National Productivity Council" in r.content

    def test_404_template_exists(self, settings):
        # Templates load without DEBUG=False as well — just verify presence
        from django.template.loader import get_template
        get_template("404.html")  # raises if missing
        get_template("500.html")
        get_template("403.html")

    def test_403_template_has_helpful_text(self):
        from django.template.loader import get_template
        t = get_template("403.html")
        rendered = t.render({})
        assert "Access denied" in rendered
        assert "Group Head" in rendered

    def test_500_template_has_helpful_text(self):
        from django.template.loader import get_template
        t = get_template("500.html")
        rendered = t.render({})
        assert "Something went wrong" in rendered
        assert "Your work is safe" in rendered
