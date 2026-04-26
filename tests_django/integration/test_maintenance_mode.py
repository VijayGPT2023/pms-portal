"""
F.5 — maintenance mode middleware tests (M0-REL-10).
"""
import pytest
from django.test import Client as TestClient

from core.models import SiteConfig

pytestmark = pytest.mark.django_db


class TestMaintenanceMode:
    def test_default_off_lets_traffic_through(self, db):
        # Without explicit setting, maintenance is OFF
        r = TestClient().get("/login/")
        assert r.status_code == 200

    def test_maintenance_on_blocks_anonymous(self, db):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "true")
        r = TestClient().get("/dashboard/")
        assert r.status_code == 503
        assert b"Maintenance" in r.content

    def test_maintenance_on_allows_login_path(self, db):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "true")
        r = TestClient().get("/login/")
        assert r.status_code == 200  # whitelisted

    def test_maintenance_on_allows_health_path(self, db):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "true")
        r = TestClient().get("/health/")
        assert r.status_code == 200  # whitelisted

    def test_maintenance_on_allows_admin_path(self, db):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "true")
        r = TestClient().get("/admin/")  # redirects to /admin/login/ but doesn't 503
        assert r.status_code in (200, 302)

    def test_staff_user_bypasses_maintenance(self, admin_user):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "true")
        client = TestClient()
        client.login(email="admin@test.gov.in", password="testpass123")
        r = client.get("/dashboard/")
        # Staff should not get 503; whatever the dashboard does (200 / 302)
        assert r.status_code != 503

    def test_non_staff_authenticated_user_blocked(self, officer_user):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "true")
        client = TestClient()
        client.login(email="officer@test.gov.in", password="testpass123")
        r = client.get("/dashboard/")
        assert r.status_code == 503

    def test_off_value_treated_as_off(self, db):
        SiteConfig.set(SiteConfig.KEY_MAINTENANCE_MODE, "false")
        r = TestClient().get("/login/")
        assert r.status_code == 200
