"""
Script to generate dummy assignment data for testing.
Creates assignments with milestones (including invoice/payment status),
expenditure items, and revenue shares.
Data structure similar to Summary Performance April-October 2025.xlsx

Physical Progress = (100% paid + 80% pending) based on invoice status
Timeline Progress = based on milestone completion vs target dates
Revenue Shared = 100% paid + 80% pending, 0% not invoiced
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from datetime import date, timedelta
from app.database import (
    init_database, get_db,
    calculate_physical_progress, calculate_timeline_progress,
    calculate_shareable_revenue, update_assignment_progress
)
from app.config import DOMAIN_OPTIONS, CLIENT_TYPE_OPTIONS, ASSIGNMENT_STATUS_OPTIONS


# Office data based on Summary Performance April-October 2025
OFFICE_PERFORMANCE_DATA = {
    'RD Chennai': {'achievement_pct': 0.27, 'training_target': 2, 'lecture_target': 3},
    'RD Bengaluru': {'achievement_pct': 0.07, 'training_target': 0, 'lecture_target': 2},
    'RD Bhubneswar': {'achievement_pct': 0.10, 'training_target': 2, 'lecture_target': 2},
    'RD Chandigarh': {'achievement_pct': 0.15, 'training_target': 1, 'lecture_target': 2},
    'RD Gandhinagar': {'achievement_pct': 0.23, 'training_target': 5, 'lecture_target': 1},
    'RD Guwahati': {'achievement_pct': 0.10, 'training_target': 2, 'lecture_target': 2},
    'RD Hyderabad': {'achievement_pct': 0.16, 'training_target': 4, 'lecture_target': 2},
    'RD Jaipur': {'achievement_pct': 0.20, 'training_target': 2, 'lecture_target': 2},
    'RD Kanpur': {'achievement_pct': 0.08, 'training_target': 1, 'lecture_target': 1},
    'RD Kolkata': {'achievement_pct': 0.11, 'training_target': 2, 'lecture_target': 2},
    'RD Mumbai': {'achievement_pct': 0.17, 'training_target': 3, 'lecture_target': 3},
    'RD Patna': {'achievement_pct': 0.20, 'training_target': 1, 'lecture_target': 1},
    'HQ': {'achievement_pct': 0.35, 'training_target': 10, 'lecture_target': 10},
    'ES Group': {'achievement_pct': 0.40, 'training_target': 3, 'lecture_target': 5},
    'IE Group': {'achievement_pct': 0.30, 'training_target': 4, 'lecture_target': 4},
    'HRM Group': {'achievement_pct': 0.25, 'training_target': 5, 'lecture_target': 3},
    'AB Group': {'achievement_pct': 0.20, 'training_target': 2, 'lecture_target': 2},
    'IT Group': {'achievement_pct': 0.15, 'training_target': 2, 'lecture_target': 2},
    'ECA Group': {'achievement_pct': 0.22, 'training_target': 3, 'lecture_target': 3},
    'EM Group': {'achievement_pct': 0.18, 'training_target': 2, 'lecture_target': 2},
    'Finance Group': {'achievement_pct': 0.12, 'training_target': 1, 'lecture_target': 1},
    'Admin Group': {'achievement_pct': 0.10, 'training_target': 1, 'lecture_target': 1},
    'IS Group': {'achievement_pct': 0.15, 'training_target': 1, 'lecture_target': 1},
    'Deputation': {'achievement_pct': 0.05, 'training_target': 0, 'lecture_target': 0},
}

# Assignment titles for different domains
ASSIGNMENT_TITLES_BY_DOMAIN = {
    'ES': [
        'Third Party Evaluation of Central Sector Scheme',
        'Impact Assessment Study of Development Program',
        'Performance Audit of Government Scheme',
        'Economic Analysis of Trade Policy',
        'Feasibility Study for Infrastructure Project',
        'Baseline Survey for Social Sector Program',
    ],
    'IE': [
        'Process Optimization Study',
        'Resource Optimization Study',
        'Productivity Improvement Study',
        'Energy Audit and Conservation Plan',
        'Lean Manufacturing Implementation',
        'Quality Management System Design',
    ],
    'HRM': [
        'Human Resource Development Plan',
        'Organizational Development Study',
        'Training Need Assessment',
        'Performance Management System Design',
        'Competency Mapping Study',
        'Manpower Planning Study',
    ],
    'IT': [
        'Digital Transformation Assessment',
        'IT Infrastructure Assessment',
        'ERP Implementation Support',
        'Data Analytics Project',
        'Cybersecurity Assessment',
    ],
    'Agri': [
        'Agricultural Supply Chain Study',
        'Farm Productivity Assessment',
        'Agri-Business Development Plan',
        'Food Processing Sector Study',
    ],
    'TM': [
        'Management Development Program',
        'Executive Development Program',
        'Leadership Training Program',
        'Skill Development Training',
    ],
    'General': [
        'Strategic Planning Study',
        'Operational Efficiency Study',
        'Capacity Building Program',
        'Advisory Services',
    ],
}

TRAINING_TITLES = [
    'Executive Development Program',
    'Leadership Excellence Workshop',
    'Project Management Training',
    'Quality Control Techniques',
    'Digital Skills Enhancement',
    'Financial Management Training',
    'Strategic HR Management',
    'Industrial Engineering Techniques',
    'Data Analytics Workshop',
    'Change Management Program',
    'Lean Six Sigma Training',
    'Performance Management Workshop',
]

CLIENTS = [
    ("Ministry of Finance", "Delhi", "Central Government"),
    ("Ministry of Commerce", "Delhi", "Central Government"),
    ("DPIIT", "Delhi", "Central Government"),
    ("Ministry of Agriculture", "Delhi", "Central Government"),
    ("Ministry of MSME", "Delhi", "Central Government"),
    ("State Government of Maharashtra", "Mumbai", "State Government"),
    ("State Government of Karnataka", "Bengaluru", "State Government"),
    ("State Government of Tamil Nadu", "Chennai", "State Government"),
    ("State Government of Gujarat", "Gandhinagar", "State Government"),
    ("State Government of Odisha", "Bhubaneswar", "State Government"),
    ("State Government of Rajasthan", "Jaipur", "State Government"),
    ("SAIL", "Delhi", "PSU"),
    ("NTPC", "Delhi", "PSU"),
    ("BHEL", "Delhi", "PSU"),
    ("GAIL", "Delhi", "PSU"),
    ("ONGC", "Delhi", "PSU"),
    ("Indian Oil", "Delhi", "PSU"),
    ("Tata Group", "Mumbai", "Private"),
    ("Reliance Industries", "Mumbai", "Private"),
    ("World Bank", "Delhi", "International"),
    ("Asian Development Bank", "Delhi", "International"),
]

VENUES = [
    "NPC Head Office, New Delhi",
    "Regional Office Conference Hall",
    "Hotel Taj Palace, New Delhi",
    "India Habitat Centre, Delhi",
    "SCOPE Complex, Delhi",
    "State Institute of Public Administration",
    "Management Development Institute",
    "Client Premises",
]

MILESTONE_TEMPLATES = {
    'ASSIGNMENT': [
        ('Inception Report', 'Submit inception report with methodology', 15),
        ('Data Collection', 'Complete field data collection and primary survey', 25),
        ('Data Analysis', 'Complete data analysis and preliminary findings', 25),
        ('Draft Report', 'Submit draft report for client review', 20),
        ('Final Report', 'Submit final report with recommendations', 15),
    ],
    'TRAINING': [
        ('Course Design', 'Finalize course content and materials', 20),
        ('Pre-training Assessment', 'Complete participant assessment', 15),
        ('Training Delivery Phase 1', 'Complete first phase of training', 30),
        ('Training Delivery Phase 2', 'Complete remaining training sessions', 25),
        ('Post-training Evaluation', 'Submit evaluation report and certificates', 10),
    ],
}


def generate_assignment_no(office_id, domain, year, serial):
    """Generate a realistic assignment number."""
    office_code = office_id.replace(' ', '').replace('Group', '')[:4].upper()
    return f"NPC/{office_code}/{domain}/P{serial:02d}/{year}-{str(year+1)[-2:]}"


def random_date_in_fy(fy_year=2025):
    """Generate a random date within the given financial year (Apr-Mar)."""
    start = date(fy_year, 4, 1)
    end = date(fy_year + 1, 3, 31)
    delta = end - start
    random_days = random.randint(0, min(delta.days, 200))  # Mostly within first 7 months
    return start + timedelta(days=random_days)


def generate_milestones(assignment_id, assignment_type, start_date, target_date, total_value, cursor):
    """
    Generate 3-5 milestones for an assignment with invoice/payment status.
    Physical progress = 100% paid + 80% pending
    """
    templates = MILESTONE_TEMPLATES.get(assignment_type, MILESTONE_TEMPLATES['ASSIGNMENT'])
    num_milestones = random.randint(3, min(5, len(templates)))
    selected = random.sample(templates, num_milestones)

    # Normalize percentages to sum to 100
    total_pct = sum(t[2] for t in selected)
    duration = max((target_date - start_date).days, 30)
    current_date = start_date

    for i, (title, desc, pct) in enumerate(selected):
        normalized_pct = round((pct / total_pct) * 100, 2)
        invoice_amount = round((normalized_pct * total_value) / 100, 2)

        # Calculate milestone target date
        days_offset = int((pct / total_pct) * duration)
        milestone_date = current_date + timedelta(days=max(days_offset, 15))
        current_date = milestone_date

        # Determine status based on current date and random factors
        today = date.today()
        invoice_raised = 0
        invoice_raised_date = None
        payment_received = 0
        payment_received_date = None
        actual_completion_date = None
        status = 'Pending'

        if milestone_date < today:
            # Past milestone - determine completion status
            completion_chance = random.random()

            if completion_chance < 0.6:  # 60% completed with payment
                status = 'Completed'
                actual_completion_date = milestone_date + timedelta(days=random.randint(-5, 10))
                invoice_raised = 1
                invoice_raised_date = actual_completion_date + timedelta(days=random.randint(1, 7))
                payment_received = 1
                payment_received_date = invoice_raised_date + timedelta(days=random.randint(15, 45))
            elif completion_chance < 0.8:  # 20% invoice raised but payment pending
                status = 'Completed'
                actual_completion_date = milestone_date + timedelta(days=random.randint(-3, 15))
                invoice_raised = 1
                invoice_raised_date = actual_completion_date + timedelta(days=random.randint(1, 7))
                # Payment not received yet
            elif completion_chance < 0.9:  # 10% delayed
                status = 'Delayed'
                invoice_raised = 0
            else:  # 10% still pending
                status = 'Pending'
                invoice_raised = 0

        elif milestone_date < today + timedelta(days=30):
            # Near-future milestone
            status = random.choice(['In Progress', 'Pending'])
            if status == 'In Progress' and random.random() < 0.3:
                # Some in-progress might have invoice raised
                invoice_raised = 1
                invoice_raised_date = today - timedelta(days=random.randint(1, 10))

        # Tentative date: default = target_date, with 30% chance TL adjusted it
        tentative_date = milestone_date
        if random.random() < 0.3:
            tentative_date = milestone_date + timedelta(days=random.randint(-7, 14))

        cursor.execute("""
            INSERT INTO milestones
            (assignment_id, milestone_no, title, description, target_date, tentative_date,
             actual_completion_date, invoice_percent, invoice_amount,
             invoice_raised, invoice_raised_date, payment_received, payment_received_date,
             revenue_percent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (assignment_id, i + 1, title, desc, milestone_date.isoformat(),
              tentative_date.isoformat(),
              actual_completion_date.isoformat() if actual_completion_date else None,
              normalized_pct, invoice_amount,
              invoice_raised, invoice_raised_date.isoformat() if invoice_raised_date else None,
              payment_received, payment_received_date.isoformat() if payment_received_date else None,
              normalized_pct, status))


def generate_expenditure(assignment_id, total_value, assignment_type, cursor):
    """
    Generate expenditure items for an assignment.
    - Assignment: estimated cost within 30% of total value
    - Training: estimated cost within 55% of total value
    """
    cursor.execute("SELECT id, head_code, category FROM expenditure_heads")
    heads = [dict(row) for row in cursor.fetchall()]

    # Expenditure ratio based on type
    if assignment_type == 'TRAINING':
        # Training: estimated cost within 55% of total value
        expenditure_ratio = random.uniform(0.35, 0.55)
    else:
        # Assignment: estimated cost within 30% of total value
        expenditure_ratio = random.uniform(0.15, 0.30)

    target_expenditure = round(total_value * expenditure_ratio, 2)

    # Group heads by category
    heads_by_category = {}
    for head in heads:
        cat = head['category']
        if cat not in heads_by_category:
            heads_by_category[cat] = []
        heads_by_category[cat].append(head)

    # Category distribution (how much of target goes to each category)
    category_dist = {
        'A': 0.55, 'B': 0.15, 'C': 0.10, 'D': 0.05, 'E': 0.10, 'F': 0.05,
    }

    # Generate random weights for each head within its category
    head_weights = {}
    for cat, cat_heads in heads_by_category.items():
        weights = [random.uniform(0.5, 1.5) for _ in cat_heads]
        total_weight = sum(weights)
        for h, w in zip(cat_heads, weights):
            head_weights[h['id']] = (cat, w / total_weight)

    # Calculate estimated amounts that sum to target
    expenditure_data = []
    for head in heads:
        cat = head['category']
        cat_budget = target_expenditure * category_dist.get(cat, 0.05)
        weight_fraction = head_weights[head['id']][1]
        estimated = round(cat_budget * weight_fraction, 2)

        # Actual is usually 80-100% of estimated for most items
        if random.random() < 0.85:  # 85% of items have actual amounts
            actual = round(estimated * random.uniform(0.80, 1.0), 2)
        else:
            actual = 0

        if estimated > 0.01:
            expenditure_data.append((head['id'], estimated, actual))

    # Insert all expenditure items
    for head_id, estimated, actual in expenditure_data:
        cursor.execute("""
            INSERT OR IGNORE INTO expenditure_items
            (assignment_id, head_id, estimated_amount, actual_amount)
            VALUES (?, ?, ?, ?)
        """, (assignment_id, head_id, estimated, actual))


def create_single_assignment(assignment_data, assignment_type='ASSIGNMENT'):
    """Create a single assignment with milestones and expenditure in its own transaction."""
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            if assignment_type == 'ASSIGNMENT':
                cursor.execute("""
                    INSERT INTO assignments (
                        assignment_no, type, title, client, client_type, city, domain,
                        office_id, status, tor_scope, work_order_date, start_date,
                        target_date, team_leader_officer_id, total_value, gross_value,
                        details_filled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, assignment_data['values'])
            else:
                cursor.execute("""
                    INSERT INTO assignments (
                        assignment_no, type, title, office_id, status, venue,
                        duration_start, duration_end, duration_days, type_of_participants,
                        faculty1_officer_id, faculty2_officer_id, team_leader_officer_id,
                        target_participants, tentative_participants, actual_participants,
                        fee_per_participant, total_value, gross_value, details_filled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, assignment_data['values'])

            # Get the assignment ID - PostgreSQL needs different approach
            from app.config import USE_POSTGRES
            if USE_POSTGRES:
                cursor.execute("SELECT id FROM assignments WHERE assignment_no = ?",
                             (assignment_data['assignment_no'],))
                row = cursor.fetchone()
                assignment_id = row['id'] if row else None
            else:
                assignment_id = cursor.lastrowid

            if assignment_id:
                # Generate milestones
                generate_milestones(
                    assignment_id, assignment_type,
                    assignment_data['start_date'], assignment_data['end_date'],
                    assignment_data['total_value'], cursor
                )
                # Generate expenditure
                generate_expenditure(
                    assignment_id, assignment_data['total_value'],
                    assignment_type, cursor
                )

            conn.commit()
            return assignment_id
        except Exception as e:
            conn.rollback()
            raise e


def generate_dummy_data():
    """Generate dummy assignments and trainings with milestones and expenditure."""
    from app.config import USE_POSTGRES

    init_database()

    # Clear existing assignment data first (separate transaction)
    print("Clearing existing assignment data...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM officer_revenue_ledger")
        cursor.execute("DELETE FROM payment_receipts")
        cursor.execute("DELETE FROM invoice_requests")
        cursor.execute("DELETE FROM expenditure_entries")
        cursor.execute("DELETE FROM expenditure_items")
        cursor.execute("DELETE FROM revenue_shares")
        cursor.execute("DELETE FROM milestones")
        cursor.execute("DELETE FROM assignments")
        conn.commit()
    print("Existing data cleared.")

    # Get offices and officers (separate read transaction)
    with get_db() as conn:
        cursor = conn.cursor()

        # Get all offices with their targets
        cursor.execute("SELECT office_id, officer_count, annual_revenue_target FROM offices")
        offices = {row['office_id']: {
            'officer_count': row['officer_count'],
            'target': row['annual_revenue_target']
        } for row in cursor.fetchall()}

        if not offices:
            print("No offices found. Please run import_officers.py first.")
            return

        # Get all officers
        cursor.execute("SELECT officer_id, office_id FROM officers WHERE is_active = 1")
        officers = [dict(row) for row in cursor.fetchall()]

        if not officers:
            print("No officers found. Please run import_officers.py first.")
            return

        officers_by_office = {}
        for o in officers:
            if o['office_id'] not in officers_by_office:
                officers_by_office[o['office_id']] = []
            officers_by_office[o['office_id']].append(o['officer_id'])

        print(f"Generating enhanced dummy data for {len(offices)} offices...")

        total_assignments = 0
        total_trainings = 0
        total_milestones = 0
        assignment_ids = []

        for office_id, office_data in offices.items():
            # Get performance data
            perf_data = OFFICE_PERFORMANCE_DATA.get(office_id, {
                'achievement_pct': random.uniform(0.1, 0.3),
                'training_target': random.randint(1, 3),
                'lecture_target': random.randint(1, 3),
            })

            target = office_data['target'] or 60
            avg_assignment_value = random.uniform(20, 50)
            num_assignments = max(3, int(target / avg_assignment_value * perf_data['achievement_pct'] * 2))

            office_officers = officers_by_office.get(office_id, [])
            if not office_officers:
                office_officers = [o['officer_id'] for o in random.sample(officers, min(3, len(officers)))]

            # Generate assignments - each in its own transaction for PostgreSQL compatibility
            for i in range(num_assignments):
                domain = random.choice(DOMAIN_OPTIONS)
                titles = ASSIGNMENT_TITLES_BY_DOMAIN.get(domain, ASSIGNMENT_TITLES_BY_DOMAIN['General'])
                title = random.choice(titles)

                assignment_no = generate_assignment_no(office_id, domain, 2025, i + 1)
                client_info = random.choice(CLIENTS)
                status = random.choice(ASSIGNMENT_STATUS_OPTIONS)

                start_date = random_date_in_fy(2025)
                duration_months = random.randint(3, 12)
                target_date = start_date + timedelta(days=duration_months * 30)

                # Financial data (without GST)
                total_value = round(random.uniform(15, 100), 2)
                gross_value = total_value

                team_leader = random.choice(office_officers) if office_officers else None

                try:
                    assignment_data = {
                        'assignment_no': assignment_no,
                        'start_date': start_date,
                        'end_date': target_date,
                        'total_value': total_value,
                        'values': (
                            assignment_no, 'ASSIGNMENT', title, client_info[0], client_info[2],
                            client_info[1], domain, office_id, status,
                            f"Terms of Reference for {title}",
                            start_date.isoformat(), start_date.isoformat(),
                            target_date.isoformat(), team_leader, total_value, gross_value, 1
                        )
                    }
                    assignment_id = create_single_assignment(assignment_data, 'ASSIGNMENT')
                    if assignment_id:
                        assignment_ids.append(assignment_id)
                        total_assignments += 1
                        total_milestones += random.randint(3, 5)
                except Exception as e:
                    print(f"  Error creating assignment {assignment_no}: {e}")

            # Generate trainings - each in its own transaction
            num_trainings = perf_data.get('training_target', 2)
            for i in range(num_trainings):
                office_code = office_id.replace(' ', '').replace('Group', '')[:5].upper()
                assignment_no = f"NPC/{office_code}/TRG/{i + 1:02d}/2025-26"
                title = random.choice(TRAINING_TITLES)
                status = random.choice(ASSIGNMENT_STATUS_OPTIONS)

                duration_start = random_date_in_fy(2025)
                duration_days = random.randint(2, 10)
                duration_end = duration_start + timedelta(days=duration_days)

                faculty1 = random.choice(office_officers) if office_officers else None
                faculty2 = random.choice(office_officers) if office_officers and random.random() > 0.5 else None
                team_leader = random.choice(office_officers) if office_officers else None

                # Training participant-based revenue
                target_participants = random.randint(15, 50)
                tentative_participants = target_participants + random.randint(-5, 10)
                if tentative_participants < 5:
                    tentative_participants = target_participants
                # actual_participants depends on status
                if status in ('COMPLETED', 'PAYMENT_RECEIVED'):
                    actual_participants = tentative_participants + random.randint(-3, 5)
                    if actual_participants < 5:
                        actual_participants = tentative_participants
                elif status in ('IN_PROGRESS',):
                    actual_participants = random.randint(0, tentative_participants)
                else:
                    actual_participants = 0
                fee_per_participant = round(random.uniform(0.1, 1.0), 2)  # in lakhs

                total_value = round(target_participants * fee_per_participant, 2)
                gross_value = total_value

                try:
                    assignment_data = {
                        'assignment_no': assignment_no,
                        'start_date': duration_start,
                        'end_date': duration_end,
                        'total_value': total_value,
                        'values': (
                            assignment_no, 'TRAINING', title, office_id, status,
                            random.choice(VENUES), duration_start.isoformat(),
                            duration_end.isoformat(), duration_days,
                            random.choice(['Senior Executives', 'Middle Management', 'Technical Staff']),
                            faculty1, faculty2, team_leader,
                            target_participants, tentative_participants, actual_participants,
                            fee_per_participant, total_value, gross_value, 1
                        )
                    }
                    assignment_id = create_single_assignment(assignment_data, 'TRAINING')
                    if assignment_id:
                        assignment_ids.append(assignment_id)
                        total_trainings += 1
                        total_milestones += random.randint(3, 5)
                except Exception as e:
                    print(f"  Error creating training {assignment_no}: {e}")

        # Calculate progress for all assignments
    # Calculate progress for all assignments (separate transaction)
    print("\nCalculating physical and timeline progress...")
    with get_db() as conn:
        cursor = conn.cursor()
        for assignment_id in assignment_ids:
            # Calculate based on milestone invoice/payment status
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN payment_received = 1 THEN invoice_percent ELSE 0 END) as paid_pct,
                    SUM(CASE WHEN invoice_raised = 1 AND payment_received = 0 THEN invoice_percent * 0.8 ELSE 0 END) as pending_pct
                FROM milestones
                WHERE assignment_id = ?
            """, (assignment_id,))
            progress = cursor.fetchone()
            physical_progress = (progress['paid_pct'] or 0) + (progress['pending_pct'] or 0)

            # Calculate invoice and payment amounts
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN payment_received = 1 THEN invoice_amount ELSE 0 END), 0) as paid_amt,
                    COALESCE(SUM(CASE WHEN invoice_raised = 1 AND payment_received = 0 THEN invoice_amount ELSE 0 END), 0) as pending_amt,
                    COALESCE(SUM(CASE WHEN invoice_raised = 1 THEN invoice_amount ELSE 0 END), 0) as invoice_amt
                FROM milestones
                WHERE assignment_id = ?
            """, (assignment_id,))
            revenue = cursor.fetchone()
            paid_amount = revenue['paid_amt'] or 0
            pending_amount = revenue['pending_amt'] or 0
            invoice_amount = revenue['invoice_amt'] or 0

            # Calculate timeline progress (simplified)
            cursor.execute("""
                SELECT
                    SUM(CASE
                        WHEN status = 'Completed' AND actual_completion_date <= target_date THEN invoice_percent
                        WHEN status = 'Completed' THEN invoice_percent * 0.7
                        WHEN status = 'Delayed' THEN invoice_percent * 0.5
                        WHEN target_date >= CURRENT_DATE THEN invoice_percent
                        ELSE invoice_percent * 0.6
                    END) as timeline_score
                FROM milestones
                WHERE assignment_id = ?
            """, (assignment_id,))
            timeline = cursor.fetchone()
            timeline_progress = timeline['timeline_score'] or 0

            # Calculate total expenditure (actual)
            cursor.execute("""
                SELECT COALESCE(SUM(actual_amount), 0) as total_exp
                FROM expenditure_items
                WHERE assignment_id = ?
            """, (assignment_id,))
            expenditure = cursor.fetchone()
            actual_expenditure = expenditure['total_exp'] or 0

            # Revenue share formula:
            # 100% of payment received + 80% of invoice raised (pending) - actual expense
            gross_shareable = paid_amount + (pending_amount * 0.8)
            shareable_revenue = max(0, gross_shareable - actual_expenditure)

            # Update assignment
            cursor.execute("""
                UPDATE assignments SET
                    physical_progress_percent = ?,
                    timeline_progress_percent = ?,
                    invoice_amount = ?,
                    amount_received = ?,
                    total_expenditure = ?,
                    total_revenue = ?,
                    surplus_deficit = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (physical_progress, timeline_progress, invoice_amount, paid_amount,
                  actual_expenditure, shareable_revenue,
                  gross_shareable - actual_expenditure, assignment_id))
        conn.commit()

    # Generate invoice_requests and payment_receipts from milestone data
    print("Generating invoice requests and payment receipts...")
    invoice_count = 0
    payment_count = 0

    def get_fy_for_date(d):
        """Return FY string like '2025-26' for a given date."""
        if d.month >= 4:
            return f"{d.year}-{str(d.year + 1)[2:]}"
        else:
            return f"{d.year - 1}-{str(d.year)[2:]}"

    # Get officers to use as requesters (pick one per office)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT officer_id, office_id FROM officers WHERE designation NOT LIKE '%Admin%'")
        all_officers_list = [dict(row) for row in cursor.fetchall()]
    officers_by_off = {}
    for o in all_officers_list:
        officers_by_off.setdefault(o['office_id'], []).append(o['officer_id'])

    with get_db() as conn:
        cursor = conn.cursor()
        # Get all milestones with invoice_raised=1
        cursor.execute("""
            SELECT m.id, m.assignment_id, m.invoice_amount, m.invoice_raised_date,
                   m.payment_received, m.payment_received_date,
                   a.team_leader_officer_id, a.office_id
            FROM milestones m
            JOIN assignments a ON m.assignment_id = a.id
            WHERE m.invoice_raised = 1 AND m.invoice_raised_date IS NOT NULL
            ORDER BY m.id
        """)
        milestones_with_invoices = [dict(row) for row in cursor.fetchall()]

        for m in milestones_with_invoices:
            inv_date = m['invoice_raised_date']
            if isinstance(inv_date, str):
                inv_date = date.fromisoformat(inv_date)
            fy_period = get_fy_for_date(inv_date)
            office_officers = officers_by_off.get(m['office_id'], [])
            requester = m['team_leader_officer_id'] or (random.choice(office_officers) if office_officers else random.choice(all_officers_list)['officer_id'])

            req_num = f"INV/{invoice_count + 1:04d}/{fy_period}"
            try:
                cursor.execute("""
                    INSERT INTO invoice_requests
                    (request_number, assignment_id, milestone_id, invoice_type, invoice_amount,
                     fy_period, description, status, requested_by, requested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req_num, m['assignment_id'], m['id'], 'SUBSEQUENT',
                    m['invoice_amount'], fy_period,
                    f"Invoice for milestone {m['id']}", 'INVOICED',
                    requester, inv_date.isoformat()
                ))
                invoice_request_id = cursor.lastrowid
                invoice_count += 1

                # Create payment receipt if payment was received
                if m['payment_received'] and m['payment_received_date']:
                    pay_date = m['payment_received_date']
                    if isinstance(pay_date, str):
                        pay_date = date.fromisoformat(pay_date)
                    pay_fy = get_fy_for_date(pay_date)
                    receipt_num = f"RCP/{payment_count + 1:04d}/{pay_fy}"
                    cursor.execute("""
                        INSERT INTO payment_receipts
                        (receipt_number, invoice_request_id, amount_received, receipt_date,
                         payment_mode, reference_number, fy_period, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        receipt_num, invoice_request_id, m['invoice_amount'],
                        pay_date.isoformat(), 'NEFT',
                        f"UTR{random.randint(100000, 999999)}", pay_fy, requester
                    ))
                    payment_count += 1
            except Exception as e:
                pass

        conn.commit()
    print(f"  Invoice requests created: {invoice_count}")
    print(f"  Payment receipts created: {payment_count}")

    # Generate expenditure_entries from expenditure_items
    print("Generating expenditure entries...")
    exp_entry_count = 0
    with get_db() as conn:
        cursor = conn.cursor()
        # Get all assignments with expenditure items
        cursor.execute("""
            SELECT ei.id as item_id, ei.assignment_id, ei.actual_amount,
                   a.start_date, a.team_leader_officer_id, a.office_id
            FROM expenditure_items ei
            JOIN assignments a ON ei.assignment_id = a.id
            WHERE ei.actual_amount > 0
        """)
        exp_items = [dict(row) for row in cursor.fetchall()]

        for ei in exp_items:
            start = ei['start_date']
            if start is None:
                start = date(2025, 4, 1)
            elif isinstance(start, str):
                start = date.fromisoformat(start)
            # Generate 1-3 entries per item spread over FY
            num_entries = random.randint(1, 3)
            remaining_amount = ei['actual_amount']
            office_off = officers_by_off.get(ei['office_id'], [])
            enterer = ei['team_leader_officer_id'] or (random.choice(office_off) if office_off else random.choice(all_officers_list)['officer_id'])

            for j in range(num_entries):
                if remaining_amount <= 0:
                    break
                if j < num_entries - 1:
                    amount = round(remaining_amount * random.uniform(0.2, 0.6), 2)
                else:
                    amount = round(remaining_amount, 2)
                remaining_amount -= amount

                entry_date = start + timedelta(days=random.randint(30, 300))
                fy_p = get_fy_for_date(entry_date)
                head_id = random.choice([1, 2, 3, 6, 9, 10])

                try:
                    cursor.execute("SAVEPOINT exp_sp")
                    cursor.execute("""
                        INSERT INTO expenditure_entries
                        (expenditure_item_id, assignment_id, head_id, entry_date, amount,
                         fy_period, description, entered_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ei['item_id'], ei['assignment_id'], head_id,
                        entry_date.isoformat(), amount, fy_p,
                        f"Expenditure entry for item {ei['item_id']}",
                        enterer
                    ))
                    cursor.execute("RELEASE SAVEPOINT exp_sp")
                    exp_entry_count += 1
                except Exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT exp_sp")
        conn.commit()
    print(f"  Expenditure entries created: {exp_entry_count}")

    # Generate revenue shares (separate transaction)
    print("Generating revenue shares...")
    share_count = 0
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, total_revenue, office_id
            FROM assignments
            WHERE total_revenue > 0
        """)
        assignments_for_shares = [dict(row) for row in cursor.fetchall()]

        for assignment in random.sample(assignments_for_shares, min(len(assignments_for_shares), int(len(assignments_for_shares) * 0.6))):
            assignment_id = assignment['id']
            shareable_revenue = assignment['total_revenue']
            office_id = assignment['office_id']

            office_officers = officers_by_office.get(office_id, [])
            if not office_officers:
                office_officers = [o['officer_id'] for o in random.sample(officers, min(3, len(officers)))]

            num_shares = min(random.randint(2, 5), len(office_officers))
            share_officers = random.sample(office_officers, num_shares)

            percentages = []
            remaining = 100.0
            for j in range(num_shares - 1):
                if remaining > 0:
                    pct = round(random.uniform(5, remaining - 5 * (num_shares - j - 1)), 2)
                    percentages.append(pct)
                    remaining -= pct
            percentages.append(round(remaining, 2))
            random.shuffle(percentages)

            for officer_id, share_pct in zip(share_officers, percentages):
                share_amount = round((share_pct * shareable_revenue) / 100, 2)
                try:
                    cursor.execute("""
                        INSERT INTO revenue_shares (assignment_id, officer_id, share_percent, share_amount)
                        VALUES (?, ?, ?, ?)
                    """, (assignment_id, officer_id, share_pct, share_amount))
                    share_count += 1
                except Exception:
                    pass
        conn.commit()

    # Create financial year targets (separate transaction)
    print("Creating financial year targets...")
    with get_db() as conn:
        cursor = conn.cursor()
        for office_id, office_data in offices.items():
            target = office_data['target'] or 60
            perf_data = OFFICE_PERFORMANCE_DATA.get(office_id, {})
            cursor.execute("""
                INSERT OR REPLACE INTO financial_year_targets
                (financial_year, office_id, annual_target, q1_target, q2_target, q3_target, q4_target,
                 training_target, lecture_target)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                '2025-26', office_id, target,
                target * 0.25, target * 0.25, target * 0.25, target * 0.25,
                perf_data.get('training_target', 2), perf_data.get('lecture_target', 2)
            ))
        conn.commit()

    print(f"\n{'='*50}")
    print(f"Enhanced dummy data generation complete!")
    print(f"  Assignments created: {total_assignments}")
    print(f"  Trainings created: {total_trainings}")
    print(f"  Milestones created: ~{total_milestones}")
    print(f"  Revenue shares created: {share_count}")
    print(f"{'='*50}")


if __name__ == "__main__":
    generate_dummy_data()
