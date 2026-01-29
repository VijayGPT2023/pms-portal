"""
Integration test conftest -- test database setup and FastAPI TestClient.
"""
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Force SQLite for integration tests
os.environ["DATABASE_URL"] = ""
os.environ["SECRET_KEY"] = "integration-test-secret-key"

from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def test_db():
    """Initialize a fresh SQLite test database."""
    import app.config as config
    import app.database as database_mod

    # Use a temp file for test DB
    test_db_path = Path(__file__).resolve().parent.parent.parent / "test_pms.db"
    config.DATABASE_PATH = test_db_path
    database_mod.DATABASE_PATH = test_db_path

    # Remove old test DB if exists
    if test_db_path.exists():
        test_db_path.unlink()

    # Initialize fresh DB
    from app.database import init_database
    init_database()

    yield test_db_path

    # Cleanup
    if test_db_path.exists():
        test_db_path.unlink()


@pytest.fixture(scope="session")
def client(test_db):
    """Create a TestClient for the FastAPI app."""
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth_cookies(client):
    """Login as admin and return cookies dict."""
    from app.auth import hash_password
    from app.database import get_db

    # Ensure admin user exists with known password
    with get_db() as conn:
        cursor = conn.cursor()
        pw_hash = hash_password("testpass123")
        cursor.execute(
            "UPDATE officers SET password_hash = ? WHERE officer_id = 'ADMIN'",
            (pw_hash,),
        )

    # Login
    response = client.post(
        "/login",
        data={"email": "admin@npcindia.gov.in", "password": "testpass123"},
        follow_redirects=False,
    )
    cookies = {}
    for key, value in response.cookies.items():
        cookies[key] = value
    return cookies


@pytest.fixture
def create_test_officer(test_db):
    """Helper to create a test officer in the DB."""
    from app.auth import hash_password
    from app.database import get_db

    created_ids = []

    def _create(officer_id, name, email, office_id="HQ", designation="Consultant", password="test123"):
        pw_hash = hash_password(password)
        with get_db() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO officers (officer_id, name, email, office_id, designation, password_hash, is_active)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (officer_id, name, email, office_id, designation, pw_hash),
                )
                created_ids.append(officer_id)
            except Exception:
                pass  # Already exists
        return officer_id

    yield _create

    # Cleanup
    with get_db() as conn:
        cursor = conn.cursor()
        for oid in created_ids:
            cursor.execute("DELETE FROM officers WHERE officer_id = ?", (oid,))
