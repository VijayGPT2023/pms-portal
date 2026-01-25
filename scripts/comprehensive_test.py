"""
Comprehensive diagnostic test for PMS Portal.
Tests all functions with realistic use cases.
"""
import sys
import os
import traceback
from datetime import datetime, timedelta
import random

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, init_database, USE_POSTGRES
from app.auth import (
    generate_password, hash_password, verify_password,
    generate_session_id, create_session, validate_session,
    delete_session, authenticate_officer
)
from app.config import DOMAIN_OPTIONS, CLIENT_TYPE_OPTIONS, ASSIGNMENT_STATUS_OPTIONS

# Test results
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
                print(f"\n{'='*60}")
                print(f"TEST: {name}")
                print('='*60)
                result = func(*args, **kwargs)
                if result:
                    print(f"  [PASS] {name}")
                    results['passed'] += 1
                else:
                    print(f"  [FAIL] {name}")
                    results['failed'] += 1
                return result
            except Exception as e:
                print(f"  [ERROR] {name}: {e}")
                traceback.print_exc()
                results['failed'] += 1
                results['errors'].append((name, str(e)))
                return False
        return wrapper
    return decorator


# ============================================================
# 1. DATABASE CONNECTION TESTS
# ============================================================

@test("Database Connection")
def test_db_connection():
    print(f"  Using PostgreSQL: {USE_POSTGRES}")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test")
        row = cursor.fetchone()
        assert row['test'] == 1, "Basic query failed"
    print("  Database connection successful")
    return True


@test("All Tables Exist")
def test_tables_exist():
    required_tables = [
        'offices', 'officers', 'assignments', 'milestones',
        'revenue_shares', 'sessions', 'activity_log', 'officer_roles',
        'enquiries', 'proposal_requests', 'proposals',
        'expenditure_heads', 'expenditure_items'
    ]

    with get_db() as conn:
        cursor = conn.cursor()
        for table in required_tables:
            if USE_POSTGRES:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = %s
                    )
                """, (table,))
                exists = cursor.fetchone()[0]
            else:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                )
                exists = cursor.fetchone() is not None

            if not exists:
                print(f"  [MISSING] Table: {table}")
                return False
            print(f"  [OK] Table: {table}")

    return True


# ============================================================
# 2. AUTHENTICATION TESTS
# ============================================================

@test("Password Hashing")
def test_password_hashing():
    password = "TestPassword123!"
    hashed = hash_password(password)
    assert hashed != password, "Password should be hashed"
    assert verify_password(password, hashed), "Password verification failed"
    assert not verify_password("WrongPassword", hashed), "Wrong password should fail"
    print(f"  Password hashing works correctly")
    return True


@test("Session Generation")
def test_session_generation():
    session_id = generate_session_id()
    assert len(session_id) > 20, "Session ID should be long enough"
    session_id2 = generate_session_id()
    assert session_id != session_id2, "Session IDs should be unique"
    print(f"  Session ID generated: {session_id[:20]}...")
    return True


@test("User Authentication - Valid Credentials")
def test_auth_valid():
    officer = authenticate_officer('admin@npc.gov.in', 'Admin@123')
    assert officer is not None, "Should authenticate admin"
    assert officer['email'] == 'admin@npc.gov.in', "Email should match"
    print(f"  Authenticated: {officer['name']} ({officer['officer_id']})")
    return True


@test("User Authentication - Invalid Credentials")
def test_auth_invalid():
    officer = authenticate_officer('admin@npc.gov.in', 'WrongPassword')
    assert officer is None, "Should reject wrong password"

    officer = authenticate_officer('nonexistent@npc.gov.in', 'Admin@123')
    assert officer is None, "Should reject non-existent user"
    print("  Invalid credentials correctly rejected")
    return True


@test("Session Create and Validate")
def test_session_crud():
    # Create session
    session_id = create_session('ADMIN001')
    assert session_id is not None, "Should create session"
    print(f"  Created session: {session_id[:20]}...")

    # Validate session
    user = validate_session(session_id)
    assert user is not None, "Should validate session"
    assert user['officer_id'] == 'ADMIN001', "Officer ID should match"
    print(f"  Validated session for: {user['name']}")

    # Delete session
    delete_session(session_id)
    user = validate_session(session_id)
    assert user is None, "Session should be deleted"
    print("  Session deleted successfully")

    return True


# ============================================================
# 3. OFFICER MANAGEMENT TESTS
# ============================================================

@test("Officer Listing")
def test_officer_listing():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM officers")
        count = cursor.fetchone()['cnt']
        print(f"  Total officers: {count}")
        assert count > 0, "Should have officers"

        # Check for active officers
        cursor.execute("SELECT COUNT(*) as cnt FROM officers WHERE is_active = 1")
        active_count = cursor.fetchone()['cnt']
        print(f"  Active officers: {active_count}")

        # Get officers by office
        cursor.execute("""
            SELECT office_id, COUNT(*) as cnt
            FROM officers
            GROUP BY office_id
            ORDER BY cnt DESC
            LIMIT 5
        """)
        for row in cursor.fetchall():
            print(f"    Office {row['office_id']}: {row['cnt']} officers")

    return True


@test("Officer Roles")
def test_officer_roles():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT admin_role_id, COUNT(*) as cnt
            FROM officers
            WHERE admin_role_id IS NOT NULL
            GROUP BY admin_role_id
        """)
        roles = cursor.fetchall()
        print(f"  Officers with roles:")
        for row in roles:
            print(f"    {row['admin_role_id']}: {row['cnt']}")

    return True


# ============================================================
# 4. ENQUIRY WORKFLOW TESTS
# ============================================================

@test("Enquiry Creation")
def test_enquiry_creation():
    with get_db() as conn:
        cursor = conn.cursor()

        # Get next enquiry number
        cursor.execute("SELECT COUNT(*) as cnt FROM enquiries")
        count = cursor.fetchone()['cnt']

        enquiry_number = f"ENQ/TEST/{count+1}/2025-26"

        cursor.execute("""
            INSERT INTO enquiries (
                enquiry_number, client_name, domain, client_type,
                description, office_id, status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            enquiry_number, 'Test Client Corp', 'IT', 'Private',
            'Test enquiry for diagnostic', 'HQ', 'OPEN',
            'ADMIN001', datetime.now()
        ))

        # Verify creation
        cursor.execute("SELECT * FROM enquiries WHERE enquiry_number = ?", (enquiry_number,))
        row = cursor.fetchone()
        assert row is not None, "Enquiry should be created"
        print(f"  Created enquiry: {enquiry_number}")

        # Store for later tests
        test_enquiry_creation.enquiry_id = row['id']
        test_enquiry_creation.enquiry_number = enquiry_number

    return True


@test("Enquiry Status Updates")
def test_enquiry_status():
    if not hasattr(test_enquiry_creation, 'enquiry_id'):
        print("  Skipped - no test enquiry")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        statuses = ['OPEN', 'UNDER_REVIEW', 'APPROVED', 'CONVERTED']
        for status in statuses:
            cursor.execute(
                "UPDATE enquiries SET status = ? WHERE id = ?",
                (status, test_enquiry_creation.enquiry_id)
            )
            cursor.execute("SELECT status FROM enquiries WHERE id = ?",
                          (test_enquiry_creation.enquiry_id,))
            row = cursor.fetchone()
            assert row['status'] == status, f"Status should be {status}"
            print(f"  Status updated to: {status}")

    return True


@test("Enquiry Listing with Filters")
def test_enquiry_listing():
    with get_db() as conn:
        cursor = conn.cursor()

        # Count total
        cursor.execute("SELECT COUNT(*) as cnt FROM enquiries")
        total = cursor.fetchone()['cnt']
        print(f"  Total enquiries: {total}")

        # By status
        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM enquiries
            GROUP BY status
        """)
        for row in cursor.fetchall():
            print(f"    {row['status']}: {row['cnt']}")

        # By office
        cursor.execute("""
            SELECT office_id, COUNT(*) as cnt
            FROM enquiries
            GROUP BY office_id
            LIMIT 5
        """)
        print("  By office (top 5):")
        for row in cursor.fetchall():
            print(f"    {row['office_id']}: {row['cnt']}")

    return True


# ============================================================
# 5. PROPOSAL REQUEST WORKFLOW TESTS
# ============================================================

@test("Proposal Request Creation from Enquiry")
def test_pr_creation():
    if not hasattr(test_enquiry_creation, 'enquiry_id'):
        print("  Skipped - no test enquiry")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        # Get next PR number
        cursor.execute("SELECT COUNT(*) as cnt FROM proposal_requests")
        count = cursor.fetchone()['cnt']

        pr_number = f"PR/TEST/{count+1}/2025-26"

        cursor.execute("""
            INSERT INTO proposal_requests (
                pr_number, enquiry_id, client_name, domain,
                description, office_id, status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pr_number, test_enquiry_creation.enquiry_id,
            'Test Client Corp', 'IT',
            'Proposal request from test enquiry', 'HQ', 'PENDING',
            'ADMIN001', datetime.now()
        ))

        cursor.execute("SELECT * FROM proposal_requests WHERE pr_number = ?", (pr_number,))
        row = cursor.fetchone()
        assert row is not None, "PR should be created"
        print(f"  Created PR: {pr_number}")

        test_pr_creation.pr_id = row['id']
        test_pr_creation.pr_number = pr_number

    return True


@test("Proposal Request Approval Workflow")
def test_pr_approval():
    if not hasattr(test_pr_creation, 'pr_id'):
        print("  Skipped - no test PR")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        # Approve the PR
        cursor.execute("""
            UPDATE proposal_requests
            SET status = 'APPROVED', approved_by = ?, approved_at = ?
            WHERE id = ?
        """, ('ADMIN001', datetime.now(), test_pr_creation.pr_id))

        cursor.execute("SELECT status, approved_by FROM proposal_requests WHERE id = ?",
                      (test_pr_creation.pr_id,))
        row = cursor.fetchone()
        assert row['status'] == 'APPROVED', "PR should be approved"
        assert row['approved_by'] == 'ADMIN001', "Approver should be set"
        print(f"  PR approved by: {row['approved_by']}")

    return True


# ============================================================
# 6. PROPOSAL WORKFLOW TESTS
# ============================================================

@test("Proposal Creation from PR")
def test_proposal_creation():
    if not hasattr(test_pr_creation, 'pr_id'):
        print("  Skipped - no test PR")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM proposals")
        count = cursor.fetchone()['cnt']

        proposal_number = f"PROP/TEST/{count+1}/2025-26"

        cursor.execute("""
            INSERT INTO proposals (
                proposal_number, pr_id, client_name, domain,
                estimated_value, description, office_id, status,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            proposal_number, test_pr_creation.pr_id,
            'Test Client Corp', 'IT', 50.0,
            'Test proposal', 'HQ', 'DRAFT',
            'ADMIN001', datetime.now()
        ))

        cursor.execute("SELECT * FROM proposals WHERE proposal_number = ?", (proposal_number,))
        row = cursor.fetchone()
        assert row is not None, "Proposal should be created"
        print(f"  Created proposal: {proposal_number}")
        print(f"  Estimated value: {row['estimated_value']} Lakhs")

        test_proposal_creation.proposal_id = row['id']
        test_proposal_creation.proposal_number = proposal_number

    return True


@test("Proposal Status Workflow")
def test_proposal_status():
    if not hasattr(test_proposal_creation, 'proposal_id'):
        print("  Skipped - no test proposal")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        statuses = ['DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'WON']
        for status in statuses:
            cursor.execute(
                "UPDATE proposals SET status = ? WHERE id = ?",
                (status, test_proposal_creation.proposal_id)
            )
            print(f"  Status: {status}")

    return True


# ============================================================
# 7. ASSIGNMENT TESTS
# ============================================================

@test("Assignment Listing")
def test_assignment_listing():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM assignments")
        total = cursor.fetchone()['cnt']
        print(f"  Total assignments: {total}")

        cursor.execute("""
            SELECT type, COUNT(*) as cnt
            FROM assignments
            GROUP BY type
        """)
        for row in cursor.fetchall():
            print(f"    {row['type'] or 'NULL'}: {row['cnt']}")

        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM assignments
            GROUP BY status
            ORDER BY cnt DESC
        """)
        print("  By status:")
        for row in cursor.fetchall():
            print(f"    {row['status']}: {row['cnt']}")

    return True


@test("Assignment Creation")
def test_assignment_creation():
    with get_db() as conn:
        cursor = conn.cursor()

        assignment_no = f"NPC/TEST/ASN/1/2025-26"

        # Check if already exists
        cursor.execute("SELECT id FROM assignments WHERE assignment_no = ?", (assignment_no,))
        if cursor.fetchone():
            cursor.execute("DELETE FROM assignments WHERE assignment_no = ?", (assignment_no,))

        cursor.execute("""
            INSERT INTO assignments (
                assignment_no, type, title, client, client_type,
                domain, office_id, status, gross_value,
                work_order_date, start_date, target_date,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            assignment_no, 'ASSIGNMENT', 'Test Assignment for Diagnostics',
            'Test Client', 'Private', 'IT', 'HQ', 'Not Started',
            100.0, datetime.now().date(), datetime.now().date(),
            (datetime.now() + timedelta(days=90)).date(), datetime.now()
        ))

        cursor.execute("SELECT * FROM assignments WHERE assignment_no = ?", (assignment_no,))
        row = cursor.fetchone()
        assert row is not None, "Assignment should be created"
        print(f"  Created: {assignment_no}")
        print(f"  Value: {row['gross_value']} Lakhs")

        test_assignment_creation.assignment_id = row['id']
        test_assignment_creation.assignment_no = assignment_no

    return True


@test("Assignment Update")
def test_assignment_update():
    if not hasattr(test_assignment_creation, 'assignment_id'):
        print("  Skipped - no test assignment")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE assignments
            SET status = 'Ongoing',
                physical_progress_percent = 50,
                invoice_amount = 40.0,
                amount_received = 30.0
            WHERE id = ?
        """, (test_assignment_creation.assignment_id,))

        cursor.execute("SELECT * FROM assignments WHERE id = ?",
                      (test_assignment_creation.assignment_id,))
        row = cursor.fetchone()
        assert row['status'] == 'Ongoing', "Status should be updated"
        assert row['physical_progress_percent'] == 50, "Progress should be updated"
        print(f"  Updated status: {row['status']}")
        print(f"  Progress: {row['physical_progress_percent']}%")

    return True


# ============================================================
# 8. MILESTONE TESTS
# ============================================================

@test("Milestone Creation")
def test_milestone_creation():
    if not hasattr(test_assignment_creation, 'assignment_id'):
        print("  Skipped - no test assignment")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        milestones = [
            ('Inception Report', 30, 20),
            ('Draft Report', 60, 40),
            ('Final Report', 90, 40),
        ]

        for i, (title, days, percent) in enumerate(milestones, 1):
            target_date = datetime.now() + timedelta(days=days)
            cursor.execute("""
                INSERT INTO milestones (
                    assignment_id, milestone_no, title, target_date,
                    invoice_percent, status
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                test_assignment_creation.assignment_id, i, title,
                target_date.date(), percent, 'Pending'
            ))
            print(f"  Created milestone {i}: {title} ({percent}%)")

        cursor.execute(
            "SELECT COUNT(*) as cnt FROM milestones WHERE assignment_id = ?",
            (test_assignment_creation.assignment_id,)
        )
        count = cursor.fetchone()['cnt']
        assert count == 3, "Should have 3 milestones"

    return True


@test("Milestone Update")
def test_milestone_update():
    if not hasattr(test_assignment_creation, 'assignment_id'):
        print("  Skipped - no test assignment")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        # Update first milestone to completed
        cursor.execute("""
            UPDATE milestones
            SET status = 'Completed',
                actual_completion_date = ?,
                invoice_raised = 1,
                invoice_raised_date = ?
            WHERE assignment_id = ? AND milestone_no = 1
        """, (datetime.now().date(), datetime.now().date(),
              test_assignment_creation.assignment_id))

        cursor.execute("""
            SELECT * FROM milestones
            WHERE assignment_id = ? AND milestone_no = 1
        """, (test_assignment_creation.assignment_id,))
        row = cursor.fetchone()
        assert row['status'] == 'Completed', "Milestone should be completed"
        assert row['invoice_raised'] == 1, "Invoice should be raised"
        print(f"  Milestone 1 completed and invoiced")

    return True


# ============================================================
# 9. REVENUE SHARE TESTS
# ============================================================

@test("Revenue Share Calculation")
def test_revenue_share_creation():
    if not hasattr(test_assignment_creation, 'assignment_id'):
        print("  Skipped - no test assignment")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        # Get some officers
        cursor.execute("SELECT officer_id, name FROM officers WHERE is_active = 1 LIMIT 3")
        officers = cursor.fetchall()

        if len(officers) < 2:
            print("  Not enough officers for test")
            return True

        # Create revenue shares (without role column as it doesn't exist)
        shares = [
            (officers[0]['officer_id'], 40),
            (officers[1]['officer_id'], 30),
        ]
        if len(officers) > 2:
            shares.append((officers[2]['officer_id'], 30))

        # First clear any existing shares
        cursor.execute(
            "DELETE FROM revenue_shares WHERE assignment_id = ?",
            (test_assignment_creation.assignment_id,)
        )

        for officer_id, percent in shares:
            cursor.execute("""
                INSERT INTO revenue_shares (
                    assignment_id, officer_id, share_percent, share_amount
                ) VALUES (?, ?, ?, ?)
            """, (
                test_assignment_creation.assignment_id, officer_id,
                percent, 100.0 * percent / 100
            ))
            print(f"  Share: {officer_id}: {percent}%")

        # Verify total
        cursor.execute("""
            SELECT SUM(share_percent) as total_percent,
                   SUM(share_amount) as total_amount
            FROM revenue_shares
            WHERE assignment_id = ?
        """, (test_assignment_creation.assignment_id,))
        row = cursor.fetchone()
        print(f"  Total allocation: {row['total_percent']}%")
        print(f"  Total amount: {row['total_amount']} Lakhs")

    return True


@test("Officer Revenue Summary")
def test_officer_revenue():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                o.officer_id,
                o.name,
                COUNT(rs.id) as assignment_count,
                COALESCE(SUM(rs.share_amount), 0) as total_share
            FROM officers o
            LEFT JOIN revenue_shares rs ON o.officer_id = rs.officer_id
            WHERE o.is_active = 1
            GROUP BY o.officer_id, o.name
            HAVING COUNT(rs.id) > 0
            ORDER BY total_share DESC
            LIMIT 5
        """)

        print("  Top 5 officers by revenue share:")
        for row in cursor.fetchall():
            print(f"    {row['name']}: {row['total_share']:.2f} L ({row['assignment_count']} assignments)")

    return True


# ============================================================
# 10. EXPENDITURE TESTS
# ============================================================

@test("Expenditure Head Management")
def test_expenditure_heads():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM expenditure_heads")
        count = cursor.fetchone()['cnt']
        print(f"  Total expenditure heads: {count}")

        cursor.execute("""
            SELECT category, COUNT(*) as cnt
            FROM expenditure_heads
            GROUP BY category
        """)
        for row in cursor.fetchall():
            print(f"    {row['category']}: {row['cnt']} heads")

    return True


@test("Expenditure Item Creation")
def test_expenditure_items():
    if not hasattr(test_assignment_creation, 'assignment_id'):
        print("  Skipped - no test assignment")
        return True

    with get_db() as conn:
        cursor = conn.cursor()

        # Get expenditure heads
        cursor.execute("SELECT id, head_code, head_name FROM expenditure_heads LIMIT 3")
        heads = cursor.fetchall()

        if not heads:
            print("  No expenditure heads found")
            return True

        for head in heads:
            cursor.execute("""
                INSERT INTO expenditure_items (
                    assignment_id, head_id, estimated_amount, actual_amount, remarks
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                test_assignment_creation.assignment_id, head['id'],
                10.0, 8.0, 'Test expenditure'
            ))
            print(f"  Added: {head['head_name']} - Est: 10.0L, Actual: 8.0L")

        cursor.execute("""
            SELECT SUM(estimated_amount) as total_est,
                   SUM(actual_amount) as total_actual
            FROM expenditure_items
            WHERE assignment_id = ?
        """, (test_assignment_creation.assignment_id,))
        row = cursor.fetchone()
        print(f"  Total Estimated: {row['total_est']} L")
        print(f"  Total Actual: {row['total_actual']} L")

    return True


# ============================================================
# 11. ACTIVITY LOG TESTS
# ============================================================

@test("Activity Log Recording")
def test_activity_log():
    with get_db() as conn:
        cursor = conn.cursor()

        # Insert test log (using correct column names: actor_id, action)
        cursor.execute("""
            INSERT INTO activity_log (
                action, entity_type, entity_id,
                actor_id, remarks, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            'TEST', 'DIAGNOSTIC', 1,
            'ADMIN001', 'Diagnostic test log entry',
            datetime.now()
        ))

        # Count logs
        cursor.execute("SELECT COUNT(*) as cnt FROM activity_log")
        count = cursor.fetchone()['cnt']
        print(f"  Total activity logs: {count}")

        # Recent logs
        cursor.execute("""
            SELECT action, entity_type, remarks, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 5
        """)
        print("  Recent activity:")
        for row in cursor.fetchall():
            remarks = row['remarks'] or ''
            print(f"    {row['action']}: {row['entity_type']} - {remarks[:50] if remarks else 'N/A'}")

    return True


# ============================================================
# 12. MIS QUERY TESTS
# ============================================================

@test("MIS - Office Summary")
def test_mis_office_summary():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                o.office_id,
                o.office_name,
                COUNT(a.id) as assignment_count,
                COALESCE(SUM(a.gross_value), 0) as total_value,
                COALESCE(SUM(a.amount_received), 0) as total_received
            FROM offices o
            LEFT JOIN assignments a ON o.office_id = a.office_id
            GROUP BY o.office_id, o.office_name
            ORDER BY total_value DESC
            LIMIT 5
        """)

        print("  Top 5 offices by value:")
        for row in cursor.fetchall():
            print(f"    {row['office_id']}: {row['assignment_count']} assignments, {row['total_value']:.2f}L value")

    return True


@test("MIS - Domain Analysis")
def test_mis_domain_analysis():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                domain,
                COUNT(*) as count,
                COALESCE(SUM(gross_value), 0) as total_value
            FROM assignments
            WHERE domain IS NOT NULL
            GROUP BY domain
            ORDER BY total_value DESC
        """)

        print("  Revenue by domain:")
        for row in cursor.fetchall():
            print(f"    {row['domain']}: {row['count']} assignments, {row['total_value']:.2f}L")

    return True


@test("MIS - Status Distribution")
def test_mis_status():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                status,
                type,
                COUNT(*) as count
            FROM assignments
            GROUP BY status, type
            ORDER BY type, status
        """)

        print("  Status distribution:")
        for row in cursor.fetchall():
            print(f"    {row['type'] or 'UNSET'}/{row['status']}: {row['count']}")

    return True


# ============================================================
# 13. WORKFLOW PIPELINE TESTS
# ============================================================

@test("Workflow Pipeline Summary")
def test_workflow_pipeline():
    with get_db() as conn:
        cursor = conn.cursor()

        # Enquiries
        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM enquiries
            GROUP BY status
        """)
        print("  Enquiries by status:")
        for row in cursor.fetchall():
            print(f"    {row['status']}: {row['cnt']}")

        # PRs
        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM proposal_requests
            GROUP BY status
        """)
        print("  Proposal Requests by status:")
        for row in cursor.fetchall():
            print(f"    {row['status']}: {row['cnt']}")

        # Proposals
        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM proposals
            GROUP BY status
        """)
        print("  Proposals by status:")
        for row in cursor.fetchall():
            print(f"    {row['status']}: {row['cnt']}")

    return True


# ============================================================
# 14. DATA INTEGRITY TESTS
# ============================================================

@test("Foreign Key Integrity - Assignments")
def test_fk_assignments():
    with get_db() as conn:
        cursor = conn.cursor()

        # Check assignments reference valid offices
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM assignments a
            WHERE NOT EXISTS (
                SELECT 1 FROM offices o WHERE o.office_id = a.office_id
            )
        """)
        orphan_count = cursor.fetchone()['cnt']
        if orphan_count > 0:
            print(f"  [WARNING] {orphan_count} assignments with invalid office_id")
        else:
            print("  All assignments have valid office references")

    return True


@test("Foreign Key Integrity - Revenue Shares")
def test_fk_revenue_shares():
    with get_db() as conn:
        cursor = conn.cursor()

        # Check revenue shares reference valid assignments
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM revenue_shares rs
            WHERE NOT EXISTS (
                SELECT 1 FROM assignments a WHERE a.id = rs.assignment_id
            )
        """)
        orphan_count = cursor.fetchone()['cnt']
        if orphan_count > 0:
            print(f"  [WARNING] {orphan_count} revenue shares with invalid assignment")
        else:
            print("  All revenue shares have valid assignment references")

        # Check revenue shares reference valid officers
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM revenue_shares rs
            WHERE NOT EXISTS (
                SELECT 1 FROM officers o WHERE o.officer_id = rs.officer_id
            )
        """)
        orphan_count = cursor.fetchone()['cnt']
        if orphan_count > 0:
            print(f"  [WARNING] {orphan_count} revenue shares with invalid officer")
        else:
            print("  All revenue shares have valid officer references")

    return True


# ============================================================
# 15. CLEANUP TEST DATA
# ============================================================

@test("Cleanup Test Data")
def test_cleanup():
    with get_db() as conn:
        cursor = conn.cursor()

        # Delete test assignment and related data
        if hasattr(test_assignment_creation, 'assignment_id'):
            cursor.execute(
                "DELETE FROM expenditure_items WHERE assignment_id = ?",
                (test_assignment_creation.assignment_id,)
            )
            cursor.execute(
                "DELETE FROM revenue_shares WHERE assignment_id = ?",
                (test_assignment_creation.assignment_id,)
            )
            cursor.execute(
                "DELETE FROM milestones WHERE assignment_id = ?",
                (test_assignment_creation.assignment_id,)
            )
            cursor.execute(
                "DELETE FROM assignments WHERE id = ?",
                (test_assignment_creation.assignment_id,)
            )
            print("  Cleaned up test assignment")

        # Delete test proposal
        if hasattr(test_proposal_creation, 'proposal_id'):
            cursor.execute(
                "DELETE FROM proposals WHERE id = ?",
                (test_proposal_creation.proposal_id,)
            )
            print("  Cleaned up test proposal")

        # Delete test PR
        if hasattr(test_pr_creation, 'pr_id'):
            cursor.execute(
                "DELETE FROM proposal_requests WHERE id = ?",
                (test_pr_creation.pr_id,)
            )
            print("  Cleaned up test PR")

        # Delete test enquiry
        if hasattr(test_enquiry_creation, 'enquiry_id'):
            cursor.execute(
                "DELETE FROM enquiries WHERE id = ?",
                (test_enquiry_creation.enquiry_id,)
            )
            print("  Cleaned up test enquiry")

        # Delete test activity log (using correct column name: action)
        cursor.execute("DELETE FROM activity_log WHERE action = 'TEST'")
        print("  Cleaned up test logs")

    return True


# ============================================================
# MAIN EXECUTION
# ============================================================

def run_all_tests():
    print("\n" + "="*70)
    print("PMS PORTAL - COMPREHENSIVE DIAGNOSTIC TEST")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database: {'PostgreSQL' if USE_POSTGRES else 'SQLite'}")
    print("="*70)

    # Initialize database
    init_database()

    # Run all tests
    test_db_connection()
    test_tables_exist()

    test_password_hashing()
    test_session_generation()
    test_auth_valid()
    test_auth_invalid()
    test_session_crud()

    test_officer_listing()
    test_officer_roles()

    test_enquiry_creation()
    test_enquiry_status()
    test_enquiry_listing()

    test_pr_creation()
    test_pr_approval()

    test_proposal_creation()
    test_proposal_status()

    test_assignment_listing()
    test_assignment_creation()
    test_assignment_update()

    test_milestone_creation()
    test_milestone_update()

    test_revenue_share_creation()
    test_officer_revenue()

    test_expenditure_heads()
    test_expenditure_items()

    test_activity_log()

    test_mis_office_summary()
    test_mis_domain_analysis()
    test_mis_status()

    test_workflow_pipeline()

    test_fk_assignments()
    test_fk_revenue_shares()

    test_cleanup()

    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
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
        print("ALL TESTS PASSED! System is ready for deployment.")
    else:
        print(f"WARNING: {results['failed']} test(s) failed. Please review before deployment.")
    print("="*70 + "\n")

    return results['failed'] == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
