"""
Root conftest.py -- shared fixtures for all test levels.
"""
import os
import sys
import pytest

# Ensure app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force SQLite for testing (never hit production PostgreSQL)
os.environ["DATABASE_URL"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"


@pytest.fixture(scope="session")
def app():
    """Create the FastAPI app instance for testing."""
    # Must import after env vars are set
    from app.main import app as fastapi_app
    return fastapi_app
