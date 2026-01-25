"""
HTTP Route Tests for PMS Portal.
Tests all web routes with actual HTTP requests.
"""
import sys
import os
import subprocess
import time
import requests
import signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import USE_POSTGRES

BASE_URL = "http://127.0.0.1:8002"
session = requests.Session()

results = {
    'passed': 0,
    'failed': 0,
    'errors': []
}


def test(name):
    """Decorator for test functions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                print(f"\n  Testing: {name}...", end=" ")
                result = func(*args, **kwargs)
                if result:
                    print("[PASS]")
                    results['passed'] += 1
                else:
                    print("[FAIL]")
                    results['failed'] += 1
                return result
            except Exception as e:
                print(f"[ERROR] {e}")
                results['failed'] += 1
                results['errors'].append((name, str(e)))
                return False
        return wrapper
    return decorator


# ============================================================
# AUTHENTICATION ROUTES
# ============================================================

@test("GET /login")
def test_login_page():
    r = session.get(f"{BASE_URL}/login")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "Login" in r.text, "Login page should contain 'Login'"
    return True


@test("POST /login (valid)")
def test_login_valid():
    r = session.post(f"{BASE_URL}/login", data={
        "email": "admin@npc.gov.in",
        "password": "Admin@123"
    }, allow_redirects=False)
    assert r.status_code == 302, f"Expected 302 redirect, got {r.status_code}"
    assert "session" in session.cookies.get_dict() or len(session.cookies) > 0, "Should set session cookie"
    return True


@test("POST /login (invalid)")
def test_login_invalid():
    temp_session = requests.Session()
    r = temp_session.post(f"{BASE_URL}/login", data={
        "email": "admin@npc.gov.in",
        "password": "WrongPassword"
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "Invalid" in r.text or "invalid" in r.text, "Should show error message"
    return True


# ============================================================
# DASHBOARD ROUTES
# ============================================================

@test("GET /dashboard")
def test_dashboard():
    r = session.get(f"{BASE_URL}/dashboard")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "Dashboard" in r.text, "Should show dashboard"
    return True


@test("GET /dashboard?show_all=true")
def test_dashboard_show_all():
    r = session.get(f"{BASE_URL}/dashboard?show_all=true")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /dashboard/summary")
def test_dashboard_summary():
    r = session.get(f"{BASE_URL}/dashboard/summary")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# ENQUIRY ROUTES
# ============================================================

@test("GET /enquiry/")
def test_enquiry_list():
    r = session.get(f"{BASE_URL}/enquiry/")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "Enquir" in r.text, "Should show enquiries"
    return True


@test("GET /enquiry/new")
def test_enquiry_new_form():
    r = session.get(f"{BASE_URL}/enquiry/new")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /enquiry/pipeline")
def test_enquiry_pipeline():
    r = session.get(f"{BASE_URL}/enquiry/pipeline")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# PROPOSAL REQUEST ROUTES
# ============================================================

@test("GET /proposal-request/")
def test_pr_list():
    r = session.get(f"{BASE_URL}/proposal-request/")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /proposal-request/pipeline")
def test_pr_pipeline():
    r = session.get(f"{BASE_URL}/proposal-request/pipeline")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# PROPOSAL ROUTES
# ============================================================

@test("GET /proposal/")
def test_proposal_list():
    r = session.get(f"{BASE_URL}/proposal/")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /proposal/pipeline")
def test_proposal_pipeline():
    r = session.get(f"{BASE_URL}/proposal/pipeline")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# ASSIGNMENT ROUTES
# ============================================================

@test("GET /assignment/new")
def test_assignment_new_form():
    r = session.get(f"{BASE_URL}/assignment/new")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /assignment/1")
def test_assignment_view():
    r = session.get(f"{BASE_URL}/assignment/1")
    # Could be 200 or 404 if ID doesn't exist
    assert r.status_code in [200, 404], f"Expected 200 or 404, got {r.status_code}"
    return True


# ============================================================
# MIS ROUTES
# ============================================================

@test("GET /mis")
def test_mis_dashboard():
    r = session.get(f"{BASE_URL}/mis")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "MIS" in r.text or "Dashboard" in r.text, "Should show MIS dashboard"
    return True


@test("GET /mis/office-summary")
def test_mis_office_summary():
    r = session.get(f"{BASE_URL}/mis/office-summary")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /mis/officer-performance")
def test_mis_officer_performance():
    r = session.get(f"{BASE_URL}/mis/officer-performance")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /mis/revenue-analysis")
def test_mis_revenue_analysis():
    r = session.get(f"{BASE_URL}/mis/revenue-analysis")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# ADMIN ROUTES
# ============================================================

@test("GET /admin/users")
def test_admin_users():
    r = session.get(f"{BASE_URL}/admin/users")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /admin/roles")
def test_admin_roles():
    r = session.get(f"{BASE_URL}/admin/roles")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /admin/activity-log")
def test_admin_activity_log():
    r = session.get(f"{BASE_URL}/admin/activity-log")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# DATA EXPORT ROUTES
# ============================================================

@test("GET /data/export")
def test_data_export_page():
    r = session.get(f"{BASE_URL}/data/export")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /data/export/assignments")
def test_export_assignments():
    r = session.get(f"{BASE_URL}/data/export/assignments")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "text/csv" in r.headers.get("content-type", "") or "application" in r.headers.get("content-type", ""), "Should return CSV/Excel"
    return True


@test("GET /data/export/officers")
def test_export_officers():
    r = session.get(f"{BASE_URL}/data/export/officers")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /data/export/enquiries")
def test_export_enquiries():
    r = session.get(f"{BASE_URL}/data/export/enquiries")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


@test("GET /data/export/workflow-pipeline")
def test_export_workflow():
    r = session.get(f"{BASE_URL}/data/export/workflow-pipeline")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# CONFIG ROUTES
# ============================================================

@test("GET /data/admin/config")
def test_admin_config():
    r = session.get(f"{BASE_URL}/data/admin/config")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# APPROVALS ROUTES
# ============================================================

@test("GET /approvals")
def test_approvals():
    r = session.get(f"{BASE_URL}/approvals")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    return True


# ============================================================
# STATIC FILES
# ============================================================

@test("GET /static/css/style.css")
def test_static_css():
    r = session.get(f"{BASE_URL}/static/css/style.css")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "text/css" in r.headers.get("content-type", ""), "Should return CSS"
    return True


# ============================================================
# LOGOUT
# ============================================================

@test("GET /logout")
def test_logout():
    r = session.get(f"{BASE_URL}/logout", allow_redirects=False)
    assert r.status_code == 302, f"Expected 302 redirect, got {r.status_code}"
    return True


# ============================================================
# UNAUTHENTICATED ACCESS
# ============================================================

@test("Protected route without auth")
def test_protected_without_auth():
    temp_session = requests.Session()
    r = temp_session.get(f"{BASE_URL}/dashboard", allow_redirects=False)
    # Should redirect to login
    assert r.status_code == 302, f"Expected 302 redirect, got {r.status_code}"
    return True


# ============================================================
# API ENDPOINTS (if any)
# ============================================================

@test("GET /openapi.json")
def test_openapi():
    r = session.get(f"{BASE_URL}/openapi.json")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "application/json" in r.headers.get("content-type", ""), "Should return JSON"
    return True


# ============================================================
# MAIN
# ============================================================

def run_tests():
    print("\n" + "="*70)
    print("PMS PORTAL - HTTP ROUTE TESTS")
    print(f"Database: {'PostgreSQL' if USE_POSTGRES else 'SQLite'}")
    print(f"Base URL: {BASE_URL}")
    print("="*70)

    # Start server
    print("\nStarting test server...")
    server = subprocess.Popen(
        ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8002"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    # Wait for server to start
    time.sleep(4)

    try:
        # Check server is running
        try:
            r = requests.get(f"{BASE_URL}/login", timeout=5)
            print("Server started successfully!")
        except:
            print("ERROR: Server failed to start!")
            return False

        print("\n" + "-"*70)
        print("AUTHENTICATION TESTS")
        print("-"*70)
        test_login_page()
        test_login_valid()
        test_login_invalid()

        print("\n" + "-"*70)
        print("DASHBOARD TESTS")
        print("-"*70)
        test_dashboard()
        test_dashboard_show_all()
        test_dashboard_summary()

        print("\n" + "-"*70)
        print("ENQUIRY TESTS")
        print("-"*70)
        test_enquiry_list()
        test_enquiry_new_form()
        test_enquiry_pipeline()

        print("\n" + "-"*70)
        print("PROPOSAL REQUEST TESTS")
        print("-"*70)
        test_pr_list()
        test_pr_pipeline()

        print("\n" + "-"*70)
        print("PROPOSAL TESTS")
        print("-"*70)
        test_proposal_list()
        test_proposal_pipeline()

        print("\n" + "-"*70)
        print("ASSIGNMENT TESTS")
        print("-"*70)
        test_assignment_new_form()
        test_assignment_view()

        print("\n" + "-"*70)
        print("MIS TESTS")
        print("-"*70)
        test_mis_dashboard()
        test_mis_office_summary()
        test_mis_officer_performance()
        test_mis_revenue_analysis()

        print("\n" + "-"*70)
        print("ADMIN TESTS")
        print("-"*70)
        test_admin_users()
        test_admin_roles()
        test_admin_activity_log()

        print("\n" + "-"*70)
        print("DATA EXPORT TESTS")
        print("-"*70)
        test_data_export_page()
        test_export_assignments()
        test_export_officers()
        test_export_enquiries()
        test_export_workflow()

        print("\n" + "-"*70)
        print("CONFIG TESTS")
        print("-"*70)
        test_admin_config()

        print("\n" + "-"*70)
        print("APPROVAL TESTS")
        print("-"*70)
        test_approvals()

        print("\n" + "-"*70)
        print("STATIC FILE TESTS")
        print("-"*70)
        test_static_css()

        print("\n" + "-"*70)
        print("SECURITY TESTS")
        print("-"*70)
        test_protected_without_auth()

        print("\n" + "-"*70)
        print("API TESTS")
        print("-"*70)
        test_openapi()

        print("\n" + "-"*70)
        print("LOGOUT TEST")
        print("-"*70)
        test_logout()

    finally:
        # Stop server
        print("\n\nStopping test server...")
        server.terminate()
        try:
            server.wait(timeout=5)
        except:
            server.kill()

    # Print summary
    print("\n" + "="*70)
    print("HTTP ROUTE TEST SUMMARY")
    print("="*70)
    print(f"  Passed: {results['passed']}")
    print(f"  Failed: {results['failed']}")
    print(f"  Total:  {results['passed'] + results['failed']}")

    if results['errors']:
        print("\nERRORS:")
        for name, error in results['errors']:
            print(f"  - {name}: {error}")

    print("\n" + "="*70)
    if results['failed'] == 0:
        print("ALL HTTP ROUTE TESTS PASSED!")
    else:
        print(f"WARNING: {results['failed']} test(s) failed.")
    print("="*70 + "\n")

    return results['failed'] == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
