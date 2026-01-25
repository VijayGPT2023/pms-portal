"""
Script to generate dummy data for the 4-stage workflow:
Enquiry → Proposal Request → Proposal → Work Order

Creates sample data for all offices with realistic scenarios including:
- Various workflow states (pending approval, approved, in-progress, converted, etc.)
- Officer allocations
- Progress updates
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from datetime import date, timedelta, datetime
from app.database import init_database, get_db

# Sample client data
CLIENTS = [
    ("Ministry of Finance", "Central Government"),
    ("Ministry of Commerce & Industry", "Central Government"),
    ("Department for Promotion of Industry", "Central Government"),
    ("Ministry of Agriculture", "Central Government"),
    ("Ministry of MSME", "Central Government"),
    ("Ministry of Rural Development", "Central Government"),
    ("Ministry of Housing & Urban Affairs", "Central Government"),
    ("NITI Aayog", "Central Government"),
    ("State Government of Maharashtra", "State Government"),
    ("State Government of Karnataka", "State Government"),
    ("State Government of Tamil Nadu", "State Government"),
    ("State Government of Gujarat", "State Government"),
    ("State Government of Odisha", "State Government"),
    ("State Government of Rajasthan", "State Government"),
    ("State Government of Uttar Pradesh", "State Government"),
    ("State Government of Madhya Pradesh", "State Government"),
    ("SAIL", "PSU"),
    ("NTPC", "PSU"),
    ("BHEL", "PSU"),
    ("GAIL", "PSU"),
    ("ONGC", "PSU"),
    ("Indian Oil Corporation", "PSU"),
    ("Coal India Limited", "PSU"),
    ("Power Grid Corporation", "PSU"),
    ("BSNL", "PSU"),
    ("Tata Steel", "Private"),
    ("Reliance Industries", "Private"),
    ("Infosys", "Private"),
    ("L&T", "Private"),
    ("Mahindra Group", "Private"),
    ("World Bank", "International"),
    ("Asian Development Bank", "International"),
    ("UNDP", "International"),
    ("GIZ", "International"),
]

# Domain-wise enquiry descriptions
ENQUIRY_DESCRIPTIONS = {
    'ES': [
        "Third Party Evaluation of Central Sector Scheme",
        "Impact Assessment Study of Development Program",
        "Performance Audit of Government Scheme",
        "Economic Analysis of Policy Implementation",
        "Feasibility Study for Infrastructure Project",
        "Baseline Survey for Social Sector Program",
        "Outcome-Budget Evaluation Study",
        "Mid-term Review of Flagship Scheme",
    ],
    'IE': [
        "Industrial Process Optimization Study",
        "Energy Audit and Conservation Planning",
        "Productivity Improvement Assessment",
        "Lean Manufacturing Implementation Support",
        "Quality Management System Development",
        "Supply Chain Optimization Study",
        "Plant Layout and Material Flow Analysis",
        "Equipment Effectiveness Study",
    ],
    'HRM': [
        "Human Resource Development Strategy",
        "Organizational Development Study",
        "Training Need Assessment",
        "Performance Management System Design",
        "Competency Framework Development",
        "Manpower Planning and Optimization",
        "Employee Engagement Study",
        "Leadership Development Program Design",
    ],
    'IT': [
        "Digital Transformation Roadmap",
        "IT Infrastructure Assessment",
        "ERP Implementation Advisory",
        "Data Analytics and Business Intelligence",
        "Cybersecurity Assessment",
        "IT Governance Framework Development",
        "Process Automation Study",
        "Cloud Migration Strategy",
    ],
    'Agri': [
        "Agricultural Supply Chain Study",
        "Farm Productivity Enhancement Program",
        "Agri-Business Development Advisory",
        "Food Processing Sector Analysis",
        "Irrigation Management Study",
        "Post-Harvest Management Assessment",
    ],
    'General': [
        "Strategic Planning Advisory",
        "Operational Excellence Study",
        "Capacity Building Program Design",
        "Best Practices Benchmarking Study",
        "Change Management Advisory",
        "Business Process Reengineering",
    ],
}

# Progress update samples
PROGRESS_UPDATES = [
    "Initial meeting with client completed. Requirements gathered.",
    "Stakeholder consultation in progress. Data collection initiated.",
    "Field survey underway. 60% primary data collected.",
    "Data analysis phase started. Preliminary findings being compiled.",
    "Draft report under preparation. Key recommendations identified.",
    "Client review meeting scheduled for next week.",
    "Awaiting additional data from client departments.",
    "Report revision based on client feedback in progress.",
    "Final presentation being prepared.",
    "Quality review completed. Ready for submission.",
]

# Rejection reasons
REJECTION_REASONS = [
    "Scope not aligned with organizational priorities",
    "Budget constraints for current financial year",
    "Similar study already in progress by another department",
    "Insufficient details provided. Please resubmit with more information.",
    "Client has not confirmed budget allocation",
]

# Drop reasons
DROP_REASONS = [
    "Client withdrew the requirement",
    "Budget not sanctioned by competent authority",
    "Merged with another ongoing project",
    "Project postponed to next financial year",
    "Scope significantly reduced - not viable",
]


def random_date_range(start_days_ago, end_days_ago):
    """Generate a random date between start_days_ago and end_days_ago from today."""
    start = date.today() - timedelta(days=start_days_ago)
    end = date.today() - timedelta(days=end_days_ago)
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def generate_enquiry_number(office_id, year, serial):
    """Generate enquiry number: ENQ/OFFICE/YYYY/NNNN"""
    office_code = office_id.replace(' ', '').replace('Group', '').replace('RD ', '')[:5].upper()
    return f"ENQ/{office_code}/{year}/{serial:04d}"


def generate_pr_number(office_id, year, serial):
    """Generate PR number: PR/OFFICE/YYYY/NNNN"""
    office_code = office_id.replace(' ', '').replace('Group', '').replace('RD ', '')[:5].upper()
    return f"PR/{office_code}/{year}/{serial:04d}"


def generate_proposal_number(office_id, year, serial):
    """Generate proposal number: PROP/OFFICE/YYYY/NNNN"""
    office_code = office_id.replace(' ', '').replace('Group', '').replace('RD ', '')[:5].upper()
    return f"PROP/{office_code}/{year}/{serial:04d}"


def generate_workflow_data():
    """Generate dummy workflow data for all offices."""
    from app.config import USE_POSTGRES

    init_database()

    # Clear existing workflow data first (separate transaction)
    print("\nClearing existing workflow data...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM proposals")
        cursor.execute("DELETE FROM proposal_requests")
        cursor.execute("DELETE FROM enquiries")
        conn.commit()
    print("Existing workflow data cleared.")

    with get_db() as conn:
        cursor = conn.cursor()

        # Get all offices
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

        if not offices:
            print("No offices found. Please run import_officers.py first.")
            return

        # Get all active officers
        cursor.execute("""
            SELECT officer_id, name, office_id, designation
            FROM officers
            WHERE is_active = 1
            ORDER BY office_id, name
        """)
        all_officers = [dict(row) for row in cursor.fetchall()]

        if not all_officers:
            print("No officers found. Please run import_officers.py first.")
            return

        # Group officers by office
        officers_by_office = {}
        for o in all_officers:
            if o['office_id'] not in officers_by_office:
                officers_by_office[o['office_id']] = []
            officers_by_office[o['office_id']].append(o)

        # Get domains
        cursor.execute("""
            SELECT option_value FROM config_options
            WHERE category = 'domain' AND is_active = 1
        """)
        domains = [row['option_value'] for row in cursor.fetchall()]
        if not domains:
            domains = list(ENQUIRY_DESCRIPTIONS.keys())

        print(f"\nGenerating workflow data for {len(offices)} offices...")
        print("=" * 60)

        total_enquiries = 0
        total_prs = 0
        total_proposals = 0

        current_year = date.today().year

        for office in offices:
            office_id = office['office_id']
            office_name = office['office_name']

            # Get officers for this office (or use random from all if none)
            office_officers = officers_by_office.get(office_id, [])
            if not office_officers:
                # Borrow officers from random offices for testing
                office_officers = random.sample(all_officers, min(3, len(all_officers)))

            # Determine number of items based on office type
            if 'HQ' in office_id or 'Group' in office_id:
                num_enquiries = random.randint(8, 15)
            else:
                num_enquiries = random.randint(4, 10)

            print(f"\n{office_name} ({office_id}):")
            print(f"  Officers: {len(office_officers)}")

            enq_serial = 1
            pr_serial = 1
            prop_serial = 1

            # ====== ENQUIRIES ======
            for i in range(num_enquiries):
                domain = random.choice(domains)
                descriptions = ENQUIRY_DESCRIPTIONS.get(domain, ENQUIRY_DESCRIPTIONS['General'])
                description = random.choice(descriptions)

                client = random.choice(CLIENTS)
                created_date = random_date_range(180, 10)
                target_date = created_date + timedelta(days=random.randint(30, 120))

                # Select creator (any officer)
                creator = random.choice(office_officers)

                # Determine status distribution:
                # 15% PENDING_APPROVAL, 10% REJECTED, 5% DROPPED
                # 30% APPROVED, 25% IN_PROGRESS, 15% CONVERTED_TO_PR
                status_roll = random.random()

                if status_roll < 0.15:
                    status = 'PENDING_APPROVAL'
                    approval_status = 'PENDING'
                    officer_id = None
                    approved_by = None
                    approved_at = None
                    rejection_reason = None
                    current_update = None
                elif status_roll < 0.25:
                    status = 'REJECTED'
                    approval_status = 'REJECTED'
                    officer_id = None
                    approver = random.choice(office_officers)
                    approved_by = approver['officer_id']
                    approved_at = (created_date + timedelta(days=random.randint(1, 5))).isoformat()
                    rejection_reason = random.choice(REJECTION_REASONS)
                    current_update = None
                elif status_roll < 0.30:
                    status = 'DROPPED'
                    approval_status = 'APPROVED'
                    officer = random.choice(office_officers)
                    officer_id = officer['officer_id']
                    approver = random.choice(office_officers)
                    approved_by = approver['officer_id']
                    approved_at = (created_date + timedelta(days=random.randint(1, 5))).isoformat()
                    rejection_reason = None
                    current_update = random.choice(DROP_REASONS)
                elif status_roll < 0.60:
                    status = 'APPROVED'
                    approval_status = 'APPROVED'
                    officer = random.choice(office_officers)
                    officer_id = officer['officer_id']
                    approver = random.choice(office_officers)
                    approved_by = approver['officer_id']
                    approved_at = (created_date + timedelta(days=random.randint(1, 5))).isoformat()
                    rejection_reason = None
                    current_update = random.choice(PROGRESS_UPDATES[:3]) if random.random() > 0.5 else None
                elif status_roll < 0.85:
                    status = 'IN_PROGRESS'
                    approval_status = 'APPROVED'
                    officer = random.choice(office_officers)
                    officer_id = officer['officer_id']
                    approver = random.choice(office_officers)
                    approved_by = approver['officer_id']
                    approved_at = (created_date + timedelta(days=random.randint(1, 5))).isoformat()
                    rejection_reason = None
                    current_update = random.choice(PROGRESS_UPDATES)
                else:
                    status = 'CONVERTED_TO_PR'
                    approval_status = 'APPROVED'
                    officer = random.choice(office_officers)
                    officer_id = officer['officer_id']
                    approver = random.choice(office_officers)
                    approved_by = approver['officer_id']
                    approved_at = (created_date + timedelta(days=random.randint(1, 5))).isoformat()
                    rejection_reason = None
                    current_update = "Converted to Proposal Request for formal proposal preparation"

                enquiry_number = generate_enquiry_number(office_id, current_year, enq_serial)
                enq_serial += 1

                try:
                    cursor.execute("""
                        INSERT INTO enquiries (
                            enquiry_number, client_name, client_type, domain, sub_domain,
                            office_id, officer_id, description, estimated_value, target_date,
                            status, approval_status, approved_by, approved_at, rejection_reason,
                            current_update, remarks, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        enquiry_number, client[0], client[1], domain,
                        f"{domain} - Specialized" if random.random() > 0.7 else None,
                        office_id, officer_id, description,
                        round(random.uniform(10, 100), 2) if random.random() > 0.3 else None,
                        target_date.isoformat(),
                        status, approval_status, approved_by, approved_at, rejection_reason,
                        current_update,
                        f"Enquiry received via {random.choice(['email', 'meeting', 'tender portal', 'reference'])}" if random.random() > 0.6 else None,
                        creator['officer_id'],
                        created_date.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"
                    ))

                    # Get the enquiry ID - PostgreSQL needs different approach
                    if USE_POSTGRES:
                        cursor.execute("SELECT id FROM enquiries WHERE enquiry_number = ?", (enquiry_number,))
                        row = cursor.fetchone()
                        enquiry_id = row['id'] if row else None
                    else:
                        enquiry_id = cursor.lastrowid
                    total_enquiries += 1

                    # Log activity
                    cursor.execute("""
                        INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks, created_at)
                        VALUES (?, 'CREATE', 'enquiry', ?, ?, ?)
                    """, (creator['officer_id'], enquiry_id, f"Created enquiry {enquiry_number}",
                          created_date.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"))

                    # ====== PROPOSAL REQUESTS (for converted enquiries) ======
                    if status == 'CONVERTED_TO_PR':
                        pr_created = created_date + timedelta(days=random.randint(5, 20))
                        pr_target = pr_created + timedelta(days=random.randint(20, 60))

                        # PR status distribution:
                        # 20% PENDING_APPROVAL, 25% APPROVED, 30% IN_PROGRESS, 25% CONVERTED_TO_PROPOSAL
                        pr_status_roll = random.random()

                        if pr_status_roll < 0.20:
                            pr_status = 'PENDING_APPROVAL'
                            pr_approval_status = 'PENDING'
                            pr_officer_id = None
                            pr_approved_by = None
                            pr_approved_at = None
                            pr_current_update = None
                        elif pr_status_roll < 0.45:
                            pr_status = 'APPROVED'
                            pr_approval_status = 'APPROVED'
                            pr_officer = random.choice(office_officers)
                            pr_officer_id = pr_officer['officer_id']
                            pr_approver = random.choice(office_officers)
                            pr_approved_by = pr_approver['officer_id']
                            pr_approved_at = (pr_created + timedelta(days=random.randint(1, 3))).isoformat()
                            pr_current_update = random.choice(PROGRESS_UPDATES[:3]) if random.random() > 0.5 else None
                        elif pr_status_roll < 0.75:
                            pr_status = 'IN_PROGRESS'
                            pr_approval_status = 'APPROVED'
                            pr_officer = random.choice(office_officers)
                            pr_officer_id = pr_officer['officer_id']
                            pr_approver = random.choice(office_officers)
                            pr_approved_by = pr_approver['officer_id']
                            pr_approved_at = (pr_created + timedelta(days=random.randint(1, 3))).isoformat()
                            pr_current_update = random.choice(PROGRESS_UPDATES)
                        else:
                            pr_status = 'CONVERTED_TO_PROPOSAL'
                            pr_approval_status = 'APPROVED'
                            pr_officer = random.choice(office_officers)
                            pr_officer_id = pr_officer['officer_id']
                            pr_approver = random.choice(office_officers)
                            pr_approved_by = pr_approver['officer_id']
                            pr_approved_at = (pr_created + timedelta(days=random.randint(1, 3))).isoformat()
                            pr_current_update = "Proposal preparation completed. Submitted for client review."

                        pr_number = generate_pr_number(office_id, current_year, pr_serial)
                        pr_serial += 1

                        cursor.execute("""
                            INSERT INTO proposal_requests (
                                pr_number, enquiry_id, client_name, client_type, domain, sub_domain,
                                office_id, officer_id, description, estimated_value, target_date,
                                status, approval_status, approved_by, approved_at, current_update,
                                remarks, created_by, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            pr_number, enquiry_id, client[0], client[1], domain,
                            f"{domain} - Specialized" if random.random() > 0.7 else None,
                            office_id, pr_officer_id, description,
                            round(random.uniform(15, 120), 2),
                            pr_target.isoformat(),
                            pr_status, pr_approval_status, pr_approved_by, pr_approved_at,
                            pr_current_update,
                            "Proposal request created from enquiry" if random.random() > 0.5 else None,
                            officer_id or creator['officer_id'],
                            pr_created.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"
                        ))

                        # Get the PR ID - PostgreSQL needs different approach
                        if USE_POSTGRES:
                            cursor.execute("SELECT id FROM proposal_requests WHERE pr_number = ?", (pr_number,))
                            row = cursor.fetchone()
                            pr_id = row['id'] if row else None
                        else:
                            pr_id = cursor.lastrowid
                        total_prs += 1

                        # Log PR creation
                        cursor.execute("""
                            INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks, created_at)
                            VALUES (?, 'CREATE', 'proposal_request', ?, ?, ?)
                        """, (officer_id or creator['officer_id'], pr_id, f"Created PR {pr_number} from enquiry",
                              pr_created.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"))

                        # ====== PROPOSALS (for converted PRs) ======
                        if pr_status == 'CONVERTED_TO_PROPOSAL':
                            prop_created = pr_created + timedelta(days=random.randint(5, 15))
                            prop_target = prop_created + timedelta(days=random.randint(30, 90))

                            estimated_value = round(random.uniform(20, 150), 2)
                            proposed_value = round(estimated_value * random.uniform(0.9, 1.1), 2)

                            # Proposal status distribution:
                            # 15% PENDING_APPROVAL, 20% IN_PROGRESS, 25% SUBMITTED,
                            # 15% UNDER_REVIEW, 10% SHORTLISTED, 10% WON, 5% LOST
                            prop_status_roll = random.random()

                            if prop_status_roll < 0.15:
                                prop_status = 'PENDING_APPROVAL'
                                prop_approval_status = 'PENDING'
                                prop_officer_id = None
                                prop_approved_by = None
                                prop_approved_at = None
                                prop_current_update = None
                                work_order_value = None
                            elif prop_status_roll < 0.35:
                                prop_status = 'IN_PROGRESS'
                                prop_approval_status = 'APPROVED'
                                prop_officer = random.choice(office_officers)
                                prop_officer_id = prop_officer['officer_id']
                                prop_approver = random.choice(office_officers)
                                prop_approved_by = prop_approver['officer_id']
                                prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()
                                prop_current_update = random.choice(PROGRESS_UPDATES)
                                work_order_value = None
                            elif prop_status_roll < 0.60:
                                prop_status = 'SUBMITTED'
                                prop_approval_status = 'APPROVED'
                                prop_officer = random.choice(office_officers)
                                prop_officer_id = prop_officer['officer_id']
                                prop_approver = random.choice(office_officers)
                                prop_approved_by = prop_approver['officer_id']
                                prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()
                                prop_current_update = "Proposal submitted to client. Awaiting feedback."
                                work_order_value = None
                            elif prop_status_roll < 0.75:
                                prop_status = 'UNDER_REVIEW'
                                prop_approval_status = 'APPROVED'
                                prop_officer = random.choice(office_officers)
                                prop_officer_id = prop_officer['officer_id']
                                prop_approver = random.choice(office_officers)
                                prop_approved_by = prop_approver['officer_id']
                                prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()
                                prop_current_update = "Client is reviewing the proposal. Technical presentation completed."
                                work_order_value = None
                            elif prop_status_roll < 0.85:
                                prop_status = 'SHORTLISTED'
                                prop_approval_status = 'APPROVED'
                                prop_officer = random.choice(office_officers)
                                prop_officer_id = prop_officer['officer_id']
                                prop_approver = random.choice(office_officers)
                                prop_approved_by = prop_approver['officer_id']
                                prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()
                                prop_current_update = "Proposal shortlisted! Final negotiations in progress."
                                work_order_value = None
                            elif prop_status_roll < 0.95:
                                prop_status = 'WON'
                                prop_approval_status = 'APPROVED'
                                prop_officer = random.choice(office_officers)
                                prop_officer_id = prop_officer['officer_id']
                                prop_approver = random.choice(office_officers)
                                prop_approved_by = prop_approver['officer_id']
                                prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()
                                prop_current_update = "Work Order received! Assignment created."
                                work_order_value = round(proposed_value * random.uniform(0.95, 1.05), 2)
                            else:
                                prop_status = 'LOST'
                                prop_approval_status = 'APPROVED'
                                prop_officer = random.choice(office_officers)
                                prop_officer_id = prop_officer['officer_id']
                                prop_approver = random.choice(office_officers)
                                prop_approved_by = prop_approver['officer_id']
                                prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()
                                prop_current_update = None
                                work_order_value = None

                            proposal_number = generate_proposal_number(office_id, current_year, prop_serial)
                            prop_serial += 1

                            cursor.execute("""
                                INSERT INTO proposals (
                                    proposal_number, pr_id, enquiry_id, client_name, client_type,
                                    domain, sub_domain, office_id, officer_id, description,
                                    estimated_value, proposed_value, work_order_value, target_date,
                                    status, approval_status, approved_by, approved_at, current_update,
                                    loss_reason, remarks, created_by, created_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                proposal_number, pr_id, enquiry_id, client[0], client[1],
                                domain, f"{domain} - Specialized" if random.random() > 0.7 else None,
                                office_id, prop_officer_id, description,
                                estimated_value, proposed_value, work_order_value,
                                prop_target.isoformat(),
                                prop_status, prop_approval_status, prop_approved_by, prop_approved_at,
                                prop_current_update,
                                "Competitor offered lower price" if prop_status == 'LOST' else None,
                                "Proposal created from PR" if random.random() > 0.5 else None,
                                pr_officer_id or creator['officer_id'],
                                prop_created.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"
                            ))

                            # Get the proposal ID - PostgreSQL needs different approach
                            if USE_POSTGRES:
                                cursor.execute("SELECT id FROM proposals WHERE proposal_number = ?", (proposal_number,))
                                row = cursor.fetchone()
                                proposal_id = row['id'] if row else None
                            else:
                                proposal_id = cursor.lastrowid
                            total_proposals += 1

                            # Log proposal creation
                            cursor.execute("""
                                INSERT INTO activity_log (actor_id, action, entity_type, entity_id, remarks, created_at)
                                VALUES (?, 'CREATE', 'proposal', ?, ?, ?)
                            """, (pr_officer_id or creator['officer_id'], proposal_id,
                                  f"Created proposal {proposal_number} from PR",
                                  prop_created.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"))

                except Exception as e:
                    print(f"    Error: {e}")

            # Also create some direct PRs (without enquiry)
            num_direct_prs = random.randint(1, 3)
            for _ in range(num_direct_prs):
                domain = random.choice(domains)
                descriptions = ENQUIRY_DESCRIPTIONS.get(domain, ENQUIRY_DESCRIPTIONS['General'])
                description = random.choice(descriptions)
                client = random.choice(CLIENTS)

                pr_created = random_date_range(90, 5)
                pr_target = pr_created + timedelta(days=random.randint(30, 60))
                creator = random.choice(office_officers)

                pr_status_roll = random.random()
                if pr_status_roll < 0.3:
                    pr_status = 'PENDING_APPROVAL'
                    pr_approval_status = 'PENDING'
                    pr_officer_id = None
                    pr_approved_by = None
                    pr_approved_at = None
                else:
                    pr_status = random.choice(['APPROVED', 'IN_PROGRESS'])
                    pr_approval_status = 'APPROVED'
                    pr_officer = random.choice(office_officers)
                    pr_officer_id = pr_officer['officer_id']
                    pr_approver = random.choice(office_officers)
                    pr_approved_by = pr_approver['officer_id']
                    pr_approved_at = (pr_created + timedelta(days=random.randint(1, 3))).isoformat()

                pr_number = generate_pr_number(office_id, current_year, pr_serial)
                pr_serial += 1

                try:
                    cursor.execute("""
                        INSERT INTO proposal_requests (
                            pr_number, enquiry_id, client_name, client_type, domain, sub_domain,
                            office_id, officer_id, description, estimated_value, target_date,
                            status, approval_status, approved_by, approved_at, current_update,
                            remarks, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pr_number, None, client[0], client[1], domain, None,
                        office_id, pr_officer_id, description,
                        round(random.uniform(15, 80), 2),
                        pr_target.isoformat(),
                        pr_status, pr_approval_status, pr_approved_by, pr_approved_at,
                        random.choice(PROGRESS_UPDATES[:5]) if pr_status == 'IN_PROGRESS' else None,
                        "Direct PR - Client approached directly",
                        creator['officer_id'],
                        pr_created.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"
                    ))
                    total_prs += 1
                except Exception as e:
                    pass

            # Create some direct proposals (without PR)
            num_direct_props = random.randint(0, 2)
            for _ in range(num_direct_props):
                domain = random.choice(domains)
                descriptions = ENQUIRY_DESCRIPTIONS.get(domain, ENQUIRY_DESCRIPTIONS['General'])
                description = random.choice(descriptions)
                client = random.choice(CLIENTS)

                prop_created = random_date_range(60, 5)
                prop_target = prop_created + timedelta(days=random.randint(30, 90))
                creator = random.choice(office_officers)

                estimated_value = round(random.uniform(15, 80), 2)
                proposed_value = round(estimated_value * random.uniform(0.9, 1.1), 2)

                prop_status = random.choice(['PENDING_APPROVAL', 'APPROVED', 'IN_PROGRESS', 'SUBMITTED'])
                if prop_status == 'PENDING_APPROVAL':
                    prop_approval_status = 'PENDING'
                    prop_officer_id = None
                    prop_approved_by = None
                    prop_approved_at = None
                else:
                    prop_approval_status = 'APPROVED'
                    prop_officer = random.choice(office_officers)
                    prop_officer_id = prop_officer['officer_id']
                    prop_approver = random.choice(office_officers)
                    prop_approved_by = prop_approver['officer_id']
                    prop_approved_at = (prop_created + timedelta(days=random.randint(1, 3))).isoformat()

                proposal_number = generate_proposal_number(office_id, current_year, prop_serial)
                prop_serial += 1

                try:
                    cursor.execute("""
                        INSERT INTO proposals (
                            proposal_number, pr_id, enquiry_id, client_name, client_type,
                            domain, sub_domain, office_id, officer_id, description,
                            estimated_value, proposed_value, target_date,
                            status, approval_status, approved_by, approved_at, current_update,
                            remarks, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        proposal_number, None, None, client[0], client[1],
                        domain, None, office_id, prop_officer_id, description,
                        estimated_value, proposed_value, prop_target.isoformat(),
                        prop_status, prop_approval_status, prop_approved_by, prop_approved_at,
                        random.choice(PROGRESS_UPDATES) if prop_status in ['IN_PROGRESS', 'SUBMITTED'] else None,
                        "Direct proposal - Repeat client",
                        creator['officer_id'],
                        prop_created.isoformat() + " " + f"{random.randint(9,17):02d}:{random.randint(0,59):02d}:00"
                    ))
                    total_proposals += 1
                except Exception as e:
                    pass

            print(f"  Created: {enq_serial-1} enquiries, {pr_serial-1} PRs, {prop_serial-1} proposals")

        print("\n" + "=" * 60)
        print("WORKFLOW DATA GENERATION COMPLETE!")
        print("=" * 60)
        print(f"  Total Enquiries:         {total_enquiries}")
        print(f"  Total Proposal Requests: {total_prs}")
        print(f"  Total Proposals:         {total_proposals}")
        print("=" * 60)

        # Print status distribution
        print("\nEnquiry Status Distribution:")
        cursor.execute("SELECT status, COUNT(*) as cnt FROM enquiries GROUP BY status ORDER BY cnt DESC")
        for row in cursor.fetchall():
            print(f"  {row['status']}: {row['cnt']}")

        print("\nProposal Request Status Distribution:")
        cursor.execute("SELECT status, COUNT(*) as cnt FROM proposal_requests GROUP BY status ORDER BY cnt DESC")
        for row in cursor.fetchall():
            print(f"  {row['status']}: {row['cnt']}")

        print("\nProposal Status Distribution:")
        cursor.execute("SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status ORDER BY cnt DESC")
        for row in cursor.fetchall():
            print(f"  {row['status']}: {row['cnt']}")


if __name__ == "__main__":
    generate_workflow_data()
