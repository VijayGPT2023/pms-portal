"""
E2E test conftest -- Playwright browser fixtures and server management.
"""
import os
import sys
import time
import subprocess
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Force SQLite for E2E tests
os.environ["DATABASE_URL"] = ""
os.environ["SECRET_KEY"] = "e2e-test-secret-key"

E2E_PORT = 8099
E2E_BASE_URL = f"http://localhost:{E2E_PORT}"


@pytest.fixture(scope="session")
def e2e_server():
    """Start a uvicorn server for E2E tests."""
    # Initialize test DB
    import app.config as config
    test_db_path = os.path.join(os.path.dirname(__file__), "..", "..", "test_e2e_pms.db")
    config.DATABASE_PATH = test_db_path

    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    from app.database import init_database
    init_database()

    # Set admin password
    from app.auth import hash_password
    from app.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        pw_hash = hash_password("e2e_admin_pass")
        cursor.execute(
            "UPDATE officers SET password_hash = ? WHERE officer_id = 'ADMIN'",
            (pw_hash,),
        )

    # Start server
    env = os.environ.copy()
    env["DATABASE_URL"] = ""
    proc = subprocess.Popen(
        [
            sys.executable, "-c",
            f"import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port={E2E_PORT})",
        ],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{E2E_BASE_URL}/login", timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("E2E server failed to start")

    yield E2E_BASE_URL

    proc.kill()
    proc.wait()
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


@pytest.fixture(scope="session")
def base_url(e2e_server):
    return e2e_server
