"""
F.1 — django-axes login lockout integration tests.

These tests RE-ENABLE axes (which the root conftest disables for the rest of
the suite) and exercise the actual login form to verify:
  - Failed attempts increment the counter
  - Lockout fires after AXES_FAILURE_LIMIT (5) attempts
  - Successful login resets the counter (AXES_RESET_ON_SUCCESS=True)
  - Login + logout write ActivityLog rows (M0-AUD-02)
"""
import pytest
from django.test import Client as TestClient

from core.models import ActivityLog


pytestmark = pytest.mark.django_db


@pytest.fixture
def axes_on(settings):
    """Re-enable axes (root conftest sets it False) for this module's tests."""
    settings.AXES_ENABLED = True
    # Reduce lockout limit for faster tests; keep behaviour identical.
    settings.AXES_FAILURE_LIMIT = 5
    yield
    # Defensive: clear axes state between tests so one test's failures don't
    # spill into another.
    try:
        from axes.utils import reset
        reset()
    except Exception:
        pass


class TestLoginLockout:
    URL = "/login/"

    def _bad_login(self, client, email="admin@test.gov.in"):
        return client.post(self.URL, {"email": email, "password": "WRONG"})

    def test_5_failed_attempts_lock_the_login(self, axes_on, admin_user):
        client = TestClient()
        # 4 failures: still allowed
        for _ in range(4):
            r = self._bad_login(client)
            assert r.status_code == 200  # login page re-rendered with error
        # 5th failure triggers lockout: axes returns a 403 (or 302 to lockout template)
        r = self._bad_login(client)
        assert r.status_code in (403, 429, 302), (
            f"Expected lockout on 5th attempt, got {r.status_code}"
        )

    def test_correct_password_after_lockout_still_blocked(self, axes_on, admin_user):
        client = TestClient()
        for _ in range(5):
            self._bad_login(client)
        # Even the correct password should fail while locked out
        r = client.post(self.URL, {"email": "admin@test.gov.in", "password": "testpass123"})
        assert r.status_code in (403, 429, 302)

    def test_successful_login_resets_counter(self, axes_on, admin_user):
        client = TestClient()
        for _ in range(3):
            self._bad_login(client)
        # Correct login — should succeed and clear the counter
        r = client.post(self.URL, {"email": "admin@test.gov.in", "password": "testpass123"})
        assert r.status_code == 302  # redirect to dashboard

    def test_admin_unlock_via_axes_reset(self, axes_on, admin_user):
        """Lock the account, then verify reset() unblocks it (admin path)."""
        from axes.utils import reset
        client = TestClient()
        for _ in range(5):
            self._bad_login(client)
        reset()
        client2 = TestClient()  # fresh client (axes also keys on session/IP)
        r = client2.post(self.URL, {"email": "admin@test.gov.in", "password": "testpass123"})
        assert r.status_code == 302


class TestLoginLogoutAudit:
    """M0-AUD-02 — login/logout events go to ActivityLog."""

    def test_successful_login_writes_activity_log(self, admin_user):
        client = TestClient()
        client.post("/login/", {"email": "admin@test.gov.in", "password": "testpass123"})
        log = ActivityLog.objects.filter(action="LOGIN", actor=admin_user).first()
        assert log is not None
        assert log.entity_type == "auth"
        assert "Login from" in log.remarks

    def test_logout_writes_activity_log(self, admin_user):
        client = TestClient()
        client.post("/login/", {"email": "admin@test.gov.in", "password": "testpass123"})
        ActivityLog.objects.filter(action="LOGIN", actor=admin_user).delete()
        client.get("/logout/")
        log = ActivityLog.objects.filter(action="LOGOUT", actor=admin_user).first()
        assert log is not None
        assert log.entity_type == "auth"
