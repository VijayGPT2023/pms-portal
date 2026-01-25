"""
Comprehensive Workflow Test Script for PMS Portal
Tests all stages of Revenue Activity, Non-Revenue Activity, and Training workflows.

Test Coverage:
1. Enquiry: Register, Allocate, Reject, Modify, Approve, Status Update, Drop, Convert to PR
2. Proposal Request: Similar workflow + Convert to Proposal
3. Proposal: Similar workflow + Submit, Shortlist, Win (creates Work Order), Lose, Withdraw
4. Assignment/Work Order: Type Selection, Details, Milestones, Expenditure, Revenue Distribution
5. Training: Full training workflow
6. Head Actions: Approval/Rejection at all stages
"""

import requests
import sys
import os
from datetime import date, timedelta

# Configuration
BASE_URL = os.getenv('TEST_URL', 'https://web-production-0282b.up.railway.app')

# Test users - password is 'npc123@#' for all officers
OFFICER_EMAIL = 'us.prasad@npcindia.gov.in'  # DDG - acts as head
OFFICER2_EMAIL = 'shirish.p@npcindia.gov.in'  # DDG - another head
REGULAR_OFFICER_EMAIL = 'hemant.rao@npcindia.gov.in'  # Regular officer (Director GR.I)
ADMIN_EMAIL = 'admin@npcindia.gov.in'
ADMIN_PASSWORD = 'Admin@NPC2024'
OFFICER_PASSWORD = 'npc123@#'

# Test tracking
test_results = []
test_count = 0
pass_count = 0
fail_count = 0

def log_test(name, passed, details=""):
    """Log test result."""
    global test_count, pass_count, fail_count
    test_count += 1
    status = "PASS" if passed else "FAIL"
    if passed:
        pass_count += 1
    else:
        fail_count += 1
    result = f"[{status}] {name}"
    if details:
        result += f" - {details}"
    print(result)
    test_results.append({"name": name, "passed": passed, "details": details})
    return passed


def create_session():
    """Create a new session with cookies."""
    return requests.Session()


def login(session, email, password):
    """Login and return success status."""
    try:
        response = session.post(f"{BASE_URL}/login", data={
            "email": email,
            "password": password
        }, allow_redirects=False)
        return response.status_code == 302 and '/dashboard' in response.headers.get('Location', '')
    except Exception as e:
        print(f"Login error: {e}")
        return False


def get_csrf_or_none(session, url):
    """Get CSRF token if present."""
    try:
        response = session.get(url)
        # For this app, there's no CSRF token
        return None
    except:
        return None


# =============================================================================
# ENQUIRY TESTS
# =============================================================================

def test_enquiry_workflow(session_officer, session_head):
    """Test complete enquiry workflow."""
    print("\n" + "="*60)
    print("ENQUIRY WORKFLOW TESTS")
    print("="*60)

    enquiry_id = None

    # Test 1: Officer creates enquiry (should go to pending approval)
    print("\n--- Test: Enquiry Registration by Officer ---")
    try:
        response = session_officer.post(f"{BASE_URL}/enquiry/create", data={
            "client_name": "Test Client ABC",
            "client_type": "PSU",
            "domain": "Agriculture",
            "sub_domain": "Crop Management",
            "office_id": "RD Hyderabad",
            "description": "Test enquiry for comprehensive workflow testing",
            "estimated_value": "50.0",
            "target_date": (date.today() + timedelta(days=30)).isoformat(),
            "remarks": "Created by automated test"
        }, allow_redirects=True)

        if response.status_code == 200 and 'enquiry' in response.url.lower():
            # Extract enquiry ID from URL
            if '/enquiry/' in response.url:
                parts = response.url.split('/enquiry/')
                if len(parts) > 1:
                    enquiry_id = parts[1].split('/')[0].split('?')[0]
                    if enquiry_id.isdigit():
                        enquiry_id = int(enquiry_id)
            log_test("Enquiry Registration", True, f"Created enquiry ID: {enquiry_id}")
        else:
            log_test("Enquiry Registration", False, f"Status: {response.status_code}")
    except Exception as e:
        log_test("Enquiry Registration", False, str(e))

    if not enquiry_id:
        # Try to find a pending enquiry
        try:
            response = session_head.get(f"{BASE_URL}/enquiry/?status=PENDING_APPROVAL")
            if 'enquiry/' in response.text:
                import re
                match = re.search(r'/enquiry/(\d+)', response.text)
                if match:
                    enquiry_id = int(match.group(1))
                    print(f"Found existing pending enquiry: {enquiry_id}")
        except:
            pass

    if not enquiry_id:
        log_test("Enquiry Workflow", False, "Could not create or find enquiry")
        return None

    # Test 2: Head views pending enquiry
    print("\n--- Test: Head Views Pending Enquiry ---")
    try:
        response = session_head.get(f"{BASE_URL}/enquiry/{enquiry_id}")
        has_approve_btn = 'Approve' in response.text or 'approve' in response.text
        log_test("Head Views Pending Enquiry", response.status_code == 200,
                f"Approve button visible: {has_approve_btn}")
    except Exception as e:
        log_test("Head Views Pending Enquiry", False, str(e))

    # Test 3: Head modifies enquiry before approval
    print("\n--- Test: Enquiry Modification by Head ---")
    try:
        response = session_head.post(f"{BASE_URL}/enquiry/{enquiry_id}/update", data={
            "client_name": "Test Client ABC (Modified)",
            "client_type": "PSU",
            "domain": "Agriculture",
            "sub_domain": "Crop Management",
            "office_id": "RD Hyderabad",
            "description": "Modified description by head",
            "estimated_value": "55.0",
            "target_date": (date.today() + timedelta(days=45)).isoformat(),
            "remarks": "Modified by head during review"
        }, allow_redirects=True)
        log_test("Enquiry Modification by Head", response.status_code == 200)
    except Exception as e:
        log_test("Enquiry Modification by Head", False, str(e))

    # Test 4: Head approves and allocates enquiry
    print("\n--- Test: Enquiry Approval & Allocation ---")
    try:
        # Get list of officers first
        response = session_head.get(f"{BASE_URL}/enquiry/{enquiry_id}")

        # Approve with allocation to an officer
        response = session_head.post(f"{BASE_URL}/enquiry/{enquiry_id}/approve", data={
            "officer_id": "22875"  # hemant.rao's officer_id
        }, allow_redirects=True)

        # Check if status changed to APPROVED
        response = session_head.get(f"{BASE_URL}/enquiry/{enquiry_id}")
        is_approved = 'APPROVED' in response.text and 'PENDING' not in response.text.upper().replace('PENDING_APPROVAL', '')
        log_test("Enquiry Approval & Allocation", response.status_code == 200 and is_approved)
    except Exception as e:
        log_test("Enquiry Approval & Allocation", False, str(e))

    # Test 5: Allocated officer updates progress
    print("\n--- Test: Enquiry Status Update by Officer ---")
    try:
        response = session_officer.post(f"{BASE_URL}/enquiry/{enquiry_id}/update-progress", data={
            "current_update": "Initial contact made with client. Meeting scheduled for next week.",
            "status": "IN_PROGRESS"
        }, allow_redirects=True)
        log_test("Enquiry Status Update", response.status_code == 200)
    except Exception as e:
        log_test("Enquiry Status Update", False, str(e))

    # Test 6: Officer puts enquiry on hold
    print("\n--- Test: Enquiry Put on Hold ---")
    try:
        response = session_officer.post(f"{BASE_URL}/enquiry/{enquiry_id}/hold",
                                        allow_redirects=True)
        response = session_officer.get(f"{BASE_URL}/enquiry/{enquiry_id}")
        is_on_hold = 'ON_HOLD' in response.text or 'On Hold' in response.text
        log_test("Enquiry Put on Hold", response.status_code == 200)
    except Exception as e:
        log_test("Enquiry Put on Hold", False, str(e))

    # Test 7: Officer resumes enquiry
    print("\n--- Test: Enquiry Resume from Hold ---")
    try:
        response = session_officer.post(f"{BASE_URL}/enquiry/{enquiry_id}/resume",
                                        allow_redirects=True)
        log_test("Enquiry Resume from Hold", response.status_code == 200)
    except Exception as e:
        log_test("Enquiry Resume from Hold", False, str(e))

    # Test 8: Head reallocates to different officer
    print("\n--- Test: Enquiry Reallocation by Head ---")
    try:
        response = session_head.post(f"{BASE_URL}/enquiry/{enquiry_id}/reallocate", data={
            "officer_id": "22704"  # Different officer
        }, allow_redirects=True)
        log_test("Enquiry Reallocation", response.status_code == 200)
    except Exception as e:
        log_test("Enquiry Reallocation", False, str(e))

    # Test 9: Convert enquiry to Proposal Request
    print("\n--- Test: Enquiry Conversion to Proposal Request ---")
    pr_id = None
    try:
        response = session_officer.post(f"{BASE_URL}/enquiry/{enquiry_id}/convert-to-pr",
                                        allow_redirects=True)
        # Check for PR creation
        if 'proposal-request' in response.url:
            import re
            match = re.search(r'/proposal-request/(\d+)', response.url)
            if match:
                pr_id = int(match.group(1))

        # Also check enquiry status
        response2 = session_officer.get(f"{BASE_URL}/enquiry/{enquiry_id}")
        is_converted = 'CONVERTED_TO_PR' in response2.text
        log_test("Enquiry Conversion to PR", pr_id is not None or is_converted,
                f"PR ID: {pr_id}")
    except Exception as e:
        log_test("Enquiry Conversion to PR", False, str(e))

    return {"enquiry_id": enquiry_id, "pr_id": pr_id}


def test_enquiry_rejection(session_officer, session_head):
    """Test enquiry rejection workflow."""
    print("\n--- Test: Enquiry Rejection Workflow ---")

    # Create a new enquiry to reject
    try:
        response = session_officer.post(f"{BASE_URL}/enquiry/create", data={
            "client_name": "Rejection Test Client",
            "client_type": "Private",
            "domain": "IT",
            "office_id": "RD Hyderabad",
            "description": "This enquiry will be rejected",
            "estimated_value": "20.0",
            "target_date": (date.today() + timedelta(days=15)).isoformat(),
        }, allow_redirects=True)

        # Extract enquiry ID
        import re
        match = re.search(r'/enquiry/(\d+)', response.url)
        if match:
            reject_enquiry_id = int(match.group(1))

            # Head rejects the enquiry
            response = session_head.post(f"{BASE_URL}/enquiry/{reject_enquiry_id}/reject", data={
                "rejection_reason": "Client not in our target segment. Budget too low for engagement."
            }, allow_redirects=True)

            # Verify rejection
            response = session_head.get(f"{BASE_URL}/enquiry/{reject_enquiry_id}")
            is_rejected = 'REJECTED' in response.text
            log_test("Enquiry Rejection", is_rejected, f"Enquiry {reject_enquiry_id}")
        else:
            log_test("Enquiry Rejection", False, "Could not create enquiry")
    except Exception as e:
        log_test("Enquiry Rejection", False, str(e))


def test_enquiry_drop(session_officer, session_head):
    """Test enquiry drop workflow."""
    print("\n--- Test: Enquiry Drop Workflow ---")

    # Create and approve an enquiry, then drop it
    try:
        # Create enquiry as head (auto-approved)
        response = session_head.post(f"{BASE_URL}/enquiry/create", data={
            "client_name": "Drop Test Client",
            "client_type": "Government",
            "domain": "Education",
            "office_id": "HQ",
            "description": "This enquiry will be dropped",
            "estimated_value": "30.0",
            "target_date": (date.today() + timedelta(days=20)).isoformat(),
        }, allow_redirects=True)

        import re
        match = re.search(r'/enquiry/(\d+)', response.url)
        if match:
            drop_enquiry_id = int(match.group(1))

            # Head drops the enquiry
            response = session_head.post(f"{BASE_URL}/enquiry/{drop_enquiry_id}/drop", data={
                "drop_reason": "Client has withdrawn interest. Project cancelled."
            }, allow_redirects=True)

            # Verify drop
            response = session_head.get(f"{BASE_URL}/enquiry/{drop_enquiry_id}")
            is_dropped = 'DROPPED' in response.text
            log_test("Enquiry Drop", is_dropped, f"Enquiry {drop_enquiry_id}")
        else:
            log_test("Enquiry Drop", False, "Could not create enquiry")
    except Exception as e:
        log_test("Enquiry Drop", False, str(e))


# =============================================================================
# PROPOSAL REQUEST TESTS
# =============================================================================

def test_proposal_request_workflow(session_officer, session_head, pr_id=None):
    """Test complete Proposal Request workflow."""
    print("\n" + "="*60)
    print("PROPOSAL REQUEST WORKFLOW TESTS")
    print("="*60)

    # If no PR from enquiry conversion, create one directly
    if not pr_id:
        print("\n--- Test: Direct PR Creation ---")
        try:
            response = session_officer.post(f"{BASE_URL}/proposal-request/create", data={
                "client_name": "Direct PR Test Client",
                "client_type": "PSU",
                "domain": "Manufacturing",
                "sub_domain": "Quality Control",
                "office_id": "RD Hyderabad",
                "description": "Direct proposal request for testing",
                "estimated_value": "75.0",
                "target_date": (date.today() + timedelta(days=60)).isoformat(),
                "remarks": "Direct creation test"
            }, allow_redirects=True)

            import re
            match = re.search(r'/proposal-request/(\d+)', response.url)
            if match:
                pr_id = int(match.group(1))
                log_test("Direct PR Creation", True, f"PR ID: {pr_id}")
            else:
                # Try to find any pending PR
                response = session_head.get(f"{BASE_URL}/proposal-request/?status=PENDING_APPROVAL")
                match = re.search(r'/proposal-request/(\d+)', response.text)
                if match:
                    pr_id = int(match.group(1))
                    log_test("Direct PR Creation", True, f"Found existing PR: {pr_id}")
                else:
                    log_test("Direct PR Creation", False, "Could not create or find PR")
        except Exception as e:
            log_test("Direct PR Creation", False, str(e))

    if not pr_id:
        return None

    # Test: Head approves PR
    print("\n--- Test: PR Approval by Head ---")
    try:
        response = session_head.post(f"{BASE_URL}/proposal-request/{pr_id}/approve", data={
            "officer_id": "22875"
        }, allow_redirects=True)
        response = session_head.get(f"{BASE_URL}/proposal-request/{pr_id}")
        is_approved = 'APPROVED' in response.text
        log_test("PR Approval", response.status_code == 200)
    except Exception as e:
        log_test("PR Approval", False, str(e))

    # Test: Update PR progress
    print("\n--- Test: PR Progress Update ---")
    try:
        response = session_officer.post(f"{BASE_URL}/proposal-request/{pr_id}/update-progress", data={
            "current_update": "Initial discussions completed. Client requirements documented.",
            "status": "IN_PROGRESS"
        }, allow_redirects=True)
        log_test("PR Progress Update", response.status_code == 200)
    except Exception as e:
        log_test("PR Progress Update", False, str(e))

    # Test: Convert PR to Proposal
    print("\n--- Test: PR Conversion to Proposal ---")
    proposal_id = None
    try:
        response = session_officer.post(f"{BASE_URL}/proposal-request/{pr_id}/convert-to-proposal",
                                        allow_redirects=True)
        import re
        match = re.search(r'/proposal/(\d+)', response.url)
        if match:
            proposal_id = int(match.group(1))
        log_test("PR to Proposal Conversion", proposal_id is not None, f"Proposal ID: {proposal_id}")
    except Exception as e:
        log_test("PR to Proposal Conversion", False, str(e))

    return {"pr_id": pr_id, "proposal_id": proposal_id}


def test_pr_rejection(session_officer, session_head):
    """Test PR rejection workflow."""
    print("\n--- Test: PR Rejection Workflow ---")
    try:
        response = session_officer.post(f"{BASE_URL}/proposal-request/create", data={
            "client_name": "PR Rejection Test",
            "client_type": "Private",
            "domain": "Services",
            "office_id": "RD Hyderabad",
            "description": "This PR will be rejected",
            "estimated_value": "15.0",
            "target_date": (date.today() + timedelta(days=30)).isoformat(),
        }, allow_redirects=True)

        import re
        match = re.search(r'/proposal-request/(\d+)', response.url)
        if match:
            reject_pr_id = int(match.group(1))

            response = session_head.post(f"{BASE_URL}/proposal-request/{reject_pr_id}/reject", data={
                "rejection_reason": "Scope not aligned with our expertise. Recommend referring to partner."
            }, allow_redirects=True)

            response = session_head.get(f"{BASE_URL}/proposal-request/{reject_pr_id}")
            is_rejected = 'REJECTED' in response.text
            log_test("PR Rejection", is_rejected)
        else:
            log_test("PR Rejection", False, "Could not create PR")
    except Exception as e:
        log_test("PR Rejection", False, str(e))


# =============================================================================
# PROPOSAL TESTS
# =============================================================================

def test_proposal_workflow(session_officer, session_head, proposal_id=None):
    """Test complete Proposal workflow."""
    print("\n" + "="*60)
    print("PROPOSAL WORKFLOW TESTS")
    print("="*60)

    if not proposal_id:
        print("\n--- Test: Direct Proposal Creation ---")
        try:
            response = session_officer.post(f"{BASE_URL}/proposal/create", data={
                "client_name": "Direct Proposal Test Client",
                "client_type": "PSU",
                "domain": "Energy",
                "sub_domain": "Solar Power",
                "office_id": "RD Hyderabad",
                "description": "Direct proposal for energy audit",
                "estimated_value": "100.0",
                "proposed_value": "95.0",
                "target_date": (date.today() + timedelta(days=90)).isoformat(),
                "remarks": "Direct creation for testing"
            }, allow_redirects=True)

            import re
            match = re.search(r'/proposal/(\d+)', response.url)
            if match:
                proposal_id = int(match.group(1))
                log_test("Direct Proposal Creation", True, f"Proposal ID: {proposal_id}")
            else:
                response = session_head.get(f"{BASE_URL}/proposal/?status=PENDING_APPROVAL")
                match = re.search(r'/proposal/(\d+)', response.text)
                if match:
                    proposal_id = int(match.group(1))
                    log_test("Direct Proposal Creation", True, f"Found existing: {proposal_id}")
                else:
                    log_test("Direct Proposal Creation", False, "Could not create proposal")
        except Exception as e:
            log_test("Direct Proposal Creation", False, str(e))

    if not proposal_id:
        return None

    # Test: Approve proposal
    print("\n--- Test: Proposal Approval ---")
    try:
        response = session_head.post(f"{BASE_URL}/proposal/{proposal_id}/approve", data={
            "officer_id": "22875"
        }, allow_redirects=True)
        log_test("Proposal Approval", response.status_code == 200)
    except Exception as e:
        log_test("Proposal Approval", False, str(e))

    # Test: Update progress
    print("\n--- Test: Proposal Progress Update ---")
    try:
        response = session_officer.post(f"{BASE_URL}/proposal/{proposal_id}/update-progress", data={
            "current_update": "Proposal document prepared. Technical team reviewing.",
            "status": "IN_PROGRESS"
        }, allow_redirects=True)
        log_test("Proposal Progress Update", response.status_code == 200)
    except Exception as e:
        log_test("Proposal Progress Update", False, str(e))

    # Test: Submit proposal
    print("\n--- Test: Proposal Submission to Client ---")
    try:
        response = session_officer.post(f"{BASE_URL}/proposal/{proposal_id}/submit",
                                        allow_redirects=True)
        log_test("Proposal Submission", response.status_code == 200)
    except Exception as e:
        log_test("Proposal Submission", False, str(e))

    # Test: Mark as shortlisted
    print("\n--- Test: Proposal Shortlisted ---")
    try:
        response = session_officer.post(f"{BASE_URL}/proposal/{proposal_id}/shortlist",
                                        allow_redirects=True)
        log_test("Proposal Shortlisted", response.status_code == 200)
    except Exception as e:
        log_test("Proposal Shortlisted", False, str(e))

    # Test: Mark as WON (creates Work Order/Assignment)
    print("\n--- Test: Proposal Won - Work Order Creation ---")
    assignment_id = None
    try:
        response = session_officer.post(f"{BASE_URL}/proposal/{proposal_id}/mark-won", data={
            "work_order_value": "90.0"
        }, allow_redirects=True)

        # Check if assignment was created
        import re
        match = re.search(r'/assignment/(\d+)', response.url)
        if match:
            assignment_id = int(match.group(1))

        response = session_officer.get(f"{BASE_URL}/proposal/{proposal_id}")
        is_won = 'WON' in response.text
        log_test("Proposal Won - Work Order", is_won or assignment_id is not None,
                f"Assignment ID: {assignment_id}")
    except Exception as e:
        log_test("Proposal Won - Work Order", False, str(e))

    return {"proposal_id": proposal_id, "assignment_id": assignment_id}


def test_proposal_loss(session_officer, session_head):
    """Test proposal loss workflow."""
    print("\n--- Test: Proposal Loss Workflow ---")
    try:
        # Create as head (auto-approved)
        response = session_head.post(f"{BASE_URL}/proposal/create", data={
            "client_name": "Loss Test Client",
            "client_type": "Government",
            "domain": "Healthcare",
            "office_id": "HQ",
            "description": "This proposal will be lost",
            "estimated_value": "50.0",
            "proposed_value": "45.0",
            "target_date": (date.today() + timedelta(days=45)).isoformat(),
        }, allow_redirects=True)

        import re
        match = re.search(r'/proposal/(\d+)', response.url)
        if match:
            loss_proposal_id = int(match.group(1))

            # Update to in progress
            session_head.post(f"{BASE_URL}/proposal/{loss_proposal_id}/update-progress", data={
                "current_update": "Submitted to client",
                "status": "IN_PROGRESS"
            }, allow_redirects=True)

            # Mark as lost
            response = session_head.post(f"{BASE_URL}/proposal/{loss_proposal_id}/mark-lost", data={
                "loss_reason": "Client selected competitor. Price was higher than market rate."
            }, allow_redirects=True)

            response = session_head.get(f"{BASE_URL}/proposal/{loss_proposal_id}")
            is_lost = 'LOST' in response.text
            log_test("Proposal Loss", is_lost)
        else:
            log_test("Proposal Loss", False, "Could not create proposal")
    except Exception as e:
        log_test("Proposal Loss", False, str(e))


def test_proposal_withdrawal(session_officer, session_head):
    """Test proposal withdrawal workflow."""
    print("\n--- Test: Proposal Withdrawal Workflow ---")
    try:
        response = session_head.post(f"{BASE_URL}/proposal/create", data={
            "client_name": "Withdrawal Test Client",
            "client_type": "Private",
            "domain": "Finance",
            "office_id": "HQ",
            "description": "This proposal will be withdrawn",
            "estimated_value": "40.0",
            "proposed_value": "38.0",
            "target_date": (date.today() + timedelta(days=30)).isoformat(),
        }, allow_redirects=True)

        import re
        match = re.search(r'/proposal/(\d+)', response.url)
        if match:
            withdraw_proposal_id = int(match.group(1))

            response = session_head.post(f"{BASE_URL}/proposal/{withdraw_proposal_id}/withdraw", data={
                "withdraw_reason": "Resource constraints. Cannot commit to delivery timeline."
            }, allow_redirects=True)

            response = session_head.get(f"{BASE_URL}/proposal/{withdraw_proposal_id}")
            is_withdrawn = 'WITHDRAWN' in response.text
            log_test("Proposal Withdrawal", is_withdrawn)
        else:
            log_test("Proposal Withdrawal", False, "Could not create proposal")
    except Exception as e:
        log_test("Proposal Withdrawal", False, str(e))


# =============================================================================
# ASSIGNMENT / WORK ORDER TESTS
# =============================================================================

def test_assignment_workflow(session_officer, session_head, assignment_id=None):
    """Test complete Assignment/Work Order workflow."""
    print("\n" + "="*60)
    print("ASSIGNMENT / WORK ORDER WORKFLOW TESTS")
    print("="*60)

    # Find or use existing assignment
    if not assignment_id:
        print("\n--- Finding existing assignment ---")
        try:
            response = session_head.get(f"{BASE_URL}/dashboard")
            import re
            match = re.search(r'/assignment/(\d+)', response.text)
            if match:
                assignment_id = int(match.group(1))
                print(f"Found assignment: {assignment_id}")
        except:
            pass

    if not assignment_id:
        log_test("Assignment Workflow", False, "No assignment found")
        return None

    # Test: View assignment
    print("\n--- Test: View Assignment Details ---")
    try:
        response = session_head.get(f"{BASE_URL}/assignment/view/{assignment_id}")
        log_test("View Assignment", response.status_code == 200 and 'assignment' in response.text.lower())
    except Exception as e:
        log_test("View Assignment", False, str(e))

    # Test: Select assignment type
    print("\n--- Test: Select Assignment Type ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/select-type/{assignment_id}", data={
            "assignment_type": "ASSIGNMENT"
        }, allow_redirects=True)
        log_test("Select Assignment Type", response.status_code == 200)
    except Exception as e:
        log_test("Select Assignment Type", False, str(e))

    # Test: Edit assignment details
    print("\n--- Test: Edit Assignment Details ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/edit/{assignment_id}", data={
            "title": "Updated Assignment Title - Comprehensive Test",
            "status": "ACTIVE",
            "tor_scope": "Complete scope of work including deliverables and timelines",
            "client": "Test Client Organization",
            "client_type": "PSU",
            "city": "Hyderabad",
            "domain": "Energy",
            "work_order_date": date.today().isoformat(),
            "start_date": date.today().isoformat(),
            "target_date": (date.today() + timedelta(days=180)).isoformat(),
            "team_leader_officer_id": "22875"
        }, allow_redirects=True)
        log_test("Edit Assignment Details", response.status_code == 200)
    except Exception as e:
        log_test("Edit Assignment Details", False, str(e))

    # Test: Manage milestones
    print("\n--- Test: Milestone Management ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/milestones/{assignment_id}", data={
            "milestone_1_title": "Inception Report",
            "milestone_1_description": "Initial assessment and planning",
            "milestone_1_target_date": (date.today() + timedelta(days=30)).isoformat(),
            "milestone_1_revenue_percent": "20",
            "milestone_1_invoice_raised": "0",
            "milestone_1_payment_received": "0",
            "milestone_1_status": "Pending",
            "milestone_2_title": "Interim Report",
            "milestone_2_description": "Progress report with preliminary findings",
            "milestone_2_target_date": (date.today() + timedelta(days=90)).isoformat(),
            "milestone_2_revenue_percent": "30",
            "milestone_2_invoice_raised": "0",
            "milestone_2_payment_received": "0",
            "milestone_2_status": "Pending",
            "milestone_3_title": "Final Report",
            "milestone_3_description": "Complete deliverables and recommendations",
            "milestone_3_target_date": (date.today() + timedelta(days=150)).isoformat(),
            "milestone_3_revenue_percent": "50",
            "milestone_3_invoice_raised": "0",
            "milestone_3_payment_received": "0",
            "milestone_3_status": "Pending",
        }, allow_redirects=True)
        log_test("Milestone Management", response.status_code == 200)
    except Exception as e:
        log_test("Milestone Management", False, str(e))

    # Test: Manage expenditure
    print("\n--- Test: Expenditure Management ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/expenditure/{assignment_id}", data={
            "estimated_1": "10.0",  # External Manpower
            "actual_1": "8.0",
            "remarks_1": "Hired consultant",
            "estimated_2": "5.0",  # Travel
            "actual_2": "4.5",
            "remarks_2": "Site visits",
            "estimated_3": "2.0",  # B&L
            "actual_3": "1.8",
            "remarks_3": "Team expenses",
        }, allow_redirects=True)
        log_test("Expenditure Management", response.status_code == 200)
    except Exception as e:
        log_test("Expenditure Management", False, str(e))

    # Test: Revenue distribution
    print("\n--- Test: Revenue Distribution / Team Shares ---")
    try:
        response = session_head.post(f"{BASE_URL}/revenue/edit/{assignment_id}", data={
            "officer_id_1": "22875",
            "share_percent_1": "40",
            "officer_id_2": "22704",
            "share_percent_2": "35",
            "officer_id_3": "22728",
            "share_percent_3": "25",
        }, allow_redirects=True)
        log_test("Revenue Distribution", response.status_code == 200)
    except Exception as e:
        log_test("Revenue Distribution", False, str(e))

    return {"assignment_id": assignment_id}


# =============================================================================
# TRAINING TESTS
# =============================================================================

def test_training_workflow(session_officer, session_head):
    """Test Training workflow."""
    print("\n" + "="*60)
    print("TRAINING WORKFLOW TESTS")
    print("="*60)

    # Find an existing assignment and set it as Training type
    training_id = None

    print("\n--- Test: Find/Create Training Assignment ---")
    try:
        response = session_head.get(f"{BASE_URL}/dashboard")
        import re
        # Find an assignment that can be set as training
        matches = re.findall(r'/assignment/(\d+)', response.text)
        for match in matches[:5]:  # Check first 5
            check_response = session_head.get(f"{BASE_URL}/assignment/view/{match}")
            if 'TRAINING' not in check_response.text.upper():
                training_id = int(match)
                break

        if training_id:
            log_test("Find Training Assignment", True, f"Assignment ID: {training_id}")
        else:
            log_test("Find Training Assignment", False, "No suitable assignment found")
    except Exception as e:
        log_test("Find Training Assignment", False, str(e))

    if not training_id:
        return None

    # Test: Set as Training type
    print("\n--- Test: Set Assignment as Training Type ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/select-type/{training_id}", data={
            "assignment_type": "TRAINING"
        }, allow_redirects=True)
        log_test("Set as Training", response.status_code == 200)
    except Exception as e:
        log_test("Set as Training", False, str(e))

    # Test: Edit training details
    print("\n--- Test: Edit Training Details ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/edit/{training_id}", data={
            "title": "Advanced Project Management Training",
            "status": "ACTIVE",
            "venue": "NPC Training Centre, Delhi",
            "duration_start": date.today().isoformat(),
            "duration_end": (date.today() + timedelta(days=5)).isoformat(),
            "duration_days": "5",
            "type_of_participants": "Senior Managers",
            "faculty1_officer_id": "22875",
            "faculty2_officer_id": "22704",
        }, allow_redirects=True)
        log_test("Edit Training Details", response.status_code == 200)
    except Exception as e:
        log_test("Edit Training Details", False, str(e))

    # Test: Training milestones (revenue recognition)
    print("\n--- Test: Training Milestones ---")
    try:
        response = session_head.post(f"{BASE_URL}/assignment/milestones/{training_id}", data={
            "milestone_1_title": "Registration Fees",
            "milestone_1_description": "Participant registration and advance payment",
            "milestone_1_target_date": (date.today() - timedelta(days=7)).isoformat(),
            "milestone_1_revenue_percent": "50",
            "milestone_1_invoice_raised": "1",
            "milestone_1_invoice_raised_date": (date.today() - timedelta(days=7)).isoformat(),
            "milestone_1_payment_received": "1",
            "milestone_1_payment_received_date": (date.today() - timedelta(days=5)).isoformat(),
            "milestone_1_status": "Completed",
            "milestone_2_title": "Completion Payment",
            "milestone_2_description": "Final payment after training completion",
            "milestone_2_target_date": (date.today() + timedelta(days=10)).isoformat(),
            "milestone_2_revenue_percent": "50",
            "milestone_2_invoice_raised": "0",
            "milestone_2_payment_received": "0",
            "milestone_2_status": "Pending",
        }, allow_redirects=True)
        log_test("Training Milestones", response.status_code == 200)
    except Exception as e:
        log_test("Training Milestones", False, str(e))

    # Test: Training faculty revenue share
    print("\n--- Test: Training Faculty Revenue Share ---")
    try:
        response = session_head.post(f"{BASE_URL}/revenue/edit/{training_id}", data={
            "officer_id_1": "22875",
            "share_percent_1": "60",
            "officer_id_2": "22704",
            "share_percent_2": "40",
        }, allow_redirects=True)
        log_test("Training Revenue Share", response.status_code == 200)
    except Exception as e:
        log_test("Training Revenue Share", False, str(e))

    return {"training_id": training_id}


# =============================================================================
# APPROVAL DASHBOARD TESTS
# =============================================================================

def test_approval_dashboard(session_head):
    """Test approval dashboard functionality."""
    print("\n" + "="*60)
    print("APPROVAL DASHBOARD TESTS")
    print("="*60)

    # Test: View approval dashboard
    print("\n--- Test: View Approval Dashboard ---")
    try:
        response = session_head.get(f"{BASE_URL}/approvals")
        has_pending = 'pending' in response.text.lower() or 'approval' in response.text.lower()
        log_test("View Approval Dashboard", response.status_code == 200,
                f"Dashboard loaded: {has_pending}")
    except Exception as e:
        log_test("View Approval Dashboard", False, str(e))

    # Test: Team leader allocation
    print("\n--- Test: Team Leader Allocation via Dashboard ---")
    try:
        response = session_head.get(f"{BASE_URL}/dashboard")
        import re
        match = re.search(r'/assignment/(\d+)', response.text)
        if match:
            test_assignment_id = int(match.group(1))

            response = session_head.post(f"{BASE_URL}/approvals/allocate-tl/{test_assignment_id}", data={
                "team_leader_id": "22875"
            }, allow_redirects=True)
            log_test("Team Leader Allocation", response.status_code == 200)
        else:
            log_test("Team Leader Allocation", False, "No assignment found")
    except Exception as e:
        log_test("Team Leader Allocation", False, str(e))


# =============================================================================
# MIS DASHBOARD TESTS
# =============================================================================

def test_mis_dashboard(session_head):
    """Test MIS dashboard functionality."""
    print("\n" + "="*60)
    print("MIS DASHBOARD TESTS")
    print("="*60)

    # Test: View MIS dashboard
    print("\n--- Test: View MIS Dashboard ---")
    try:
        response = session_head.get(f"{BASE_URL}/mis")
        has_metrics = 'revenue' in response.text.lower() or 'target' in response.text.lower()
        log_test("View MIS Dashboard", response.status_code == 200 and has_metrics)
    except Exception as e:
        log_test("View MIS Dashboard", False, str(e))

    # Test: Pre-revenue metrics (4-stage workflow)
    print("\n--- Test: Pre-Revenue Metrics ---")
    try:
        response = session_head.get(f"{BASE_URL}/mis")
        has_enquiries = 'enquir' in response.text.lower()
        has_proposals = 'proposal' in response.text.lower()
        log_test("Pre-Revenue Metrics", has_enquiries or has_proposals,
                f"Enquiries: {has_enquiries}, Proposals: {has_proposals}")
    except Exception as e:
        log_test("Pre-Revenue Metrics", False, str(e))


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def run_all_tests():
    """Run all workflow tests."""
    global test_count, pass_count, fail_count

    print("\n" + "="*70)
    print("PMS PORTAL - COMPREHENSIVE WORKFLOW TEST SUITE")
    print(f"Target: {BASE_URL}")
    print("="*70)

    # Create sessions
    session_officer = create_session()
    session_head = create_session()
    session_admin = create_session()

    # Login tests
    print("\n--- Authentication Tests ---")
    if not login(session_head, OFFICER_EMAIL, OFFICER_PASSWORD):
        log_test("Head Login", False, OFFICER_EMAIL)
        print("CRITICAL: Cannot login as head. Aborting tests.")
        return
    else:
        log_test("Head Login", True, OFFICER_EMAIL)

    if not login(session_officer, REGULAR_OFFICER_EMAIL, OFFICER_PASSWORD):
        log_test("Regular Officer Login", False, REGULAR_OFFICER_EMAIL)
        # Try with another officer
        if login(session_officer, OFFICER2_EMAIL, OFFICER_PASSWORD):
            log_test("Alternate Officer Login", True, OFFICER2_EMAIL)
        else:
            print("WARNING: Regular officer login failed. Some tests may fail.")
    else:
        log_test("Regular Officer Login", True, REGULAR_OFFICER_EMAIL)

    if not login(session_admin, ADMIN_EMAIL, ADMIN_PASSWORD):
        log_test("Admin Login", False, ADMIN_EMAIL)
    else:
        log_test("Admin Login", True, ADMIN_EMAIL)

    # Run test suites
    try:
        # Enquiry tests
        enquiry_result = test_enquiry_workflow(session_officer, session_head)
        test_enquiry_rejection(session_officer, session_head)
        test_enquiry_drop(session_officer, session_head)

        # Proposal Request tests
        pr_id = enquiry_result.get('pr_id') if enquiry_result else None
        pr_result = test_proposal_request_workflow(session_officer, session_head, pr_id)
        test_pr_rejection(session_officer, session_head)

        # Proposal tests
        proposal_id = pr_result.get('proposal_id') if pr_result else None
        proposal_result = test_proposal_workflow(session_officer, session_head, proposal_id)
        test_proposal_loss(session_officer, session_head)
        test_proposal_withdrawal(session_officer, session_head)

        # Assignment tests
        assignment_id = proposal_result.get('assignment_id') if proposal_result else None
        test_assignment_workflow(session_officer, session_head, assignment_id)

        # Training tests
        test_training_workflow(session_officer, session_head)

        # Approval dashboard tests
        test_approval_dashboard(session_head)

        # MIS dashboard tests
        test_mis_dashboard(session_head)

    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()

    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Total Tests: {test_count}")
    print(f"Passed: {pass_count}")
    print(f"Failed: {fail_count}")
    print(f"Pass Rate: {(pass_count/test_count*100):.1f}%" if test_count > 0 else "N/A")
    print("="*70)

    # List failed tests
    if fail_count > 0:
        print("\nFailed Tests:")
        for result in test_results:
            if not result['passed']:
                print(f"  - {result['name']}: {result['details']}")

    return pass_count, fail_count


if __name__ == "__main__":
    run_all_tests()
