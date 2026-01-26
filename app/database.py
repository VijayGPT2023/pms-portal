"""
Database connection and session management.
Supports both SQLite (local development) and PostgreSQL (production on Render).
Enhanced with version history, invoice/payment tracking, and timeline progress.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.config import DATABASE_PATH, DATABASE_URL, USE_POSTGRES

# PostgreSQL support
if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor


class DictRow:
    """Wrapper to make psycopg2 results behave like sqlite3.Row"""
    def __init__(self, data):
        self._data = data
        self._keys = list(data.keys()) if data else []

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[self._keys[key]]
        return self._data[key]

    def __iter__(self):
        return iter(self._data.values())

    def keys(self):
        return self._keys


def get_db_connection():
    """Create a database connection with row factory."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(str(DATABASE_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


class PostgresCursorWrapper:
    """Wrapper to make PostgreSQL cursor behave like SQLite cursor"""
    def __init__(self, cursor, conn=None):
        self._cursor = cursor
        self._conn = conn
        self._savepoint_counter = 0

    def execute(self, query, params=None):
        # Convert SQLite ? placeholders to PostgreSQL %s
        query = query.replace('?', '%s')
        # Convert AUTOINCREMENT to SERIAL for PostgreSQL
        query = query.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        # Convert INSERT OR IGNORE to INSERT ... ON CONFLICT DO NOTHING
        if 'INSERT OR IGNORE' in query.upper():
            query = query.replace('INSERT OR IGNORE', 'INSERT')
            query = query.replace('insert or ignore', 'INSERT')
            # Add ON CONFLICT DO NOTHING at the end
            query = query.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
        # Convert INSERT OR REPLACE to PostgreSQL UPSERT
        if 'INSERT OR REPLACE' in query.upper():
            query = query.replace('INSERT OR REPLACE', 'INSERT')
            query = query.replace('insert or replace', 'INSERT')
            # This is simplified - full UPSERT would need more logic
            query = query.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
        # Convert SQLite PRAGMA (ignore in PostgreSQL)
        if query.strip().upper().startswith('PRAGMA'):
            return self
        # Handle ALTER TABLE ADD COLUMN - use savepoint to handle errors gracefully
        if 'ALTER TABLE' in query.upper() and 'ADD COLUMN' in query.upper():
            self._savepoint_counter += 1
            savepoint_name = f"sp_{self._savepoint_counter}"
            try:
                self._cursor.execute(f"SAVEPOINT {savepoint_name}")
                if params:
                    self._cursor.execute(query, params)
                else:
                    self._cursor.execute(query)
                self._cursor.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            except Exception as e:
                # Column might already exist - rollback to savepoint
                self._cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            return self
        if params:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)
        return self

    def executemany(self, query, params_list):
        query = query.replace('?', '%s')
        for params in params_list:
            self._cursor.execute(query, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return DictRow(row) if row else None

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictRow(row) for row in rows]

    @property
    def lastrowid(self):
        # PostgreSQL uses RETURNING, but for compatibility we try to get it
        try:
            self._cursor.execute("SELECT lastval()")
            return self._cursor.fetchone()['lastval']
        except:
            return None

    @property
    def rowcount(self):
        return self._cursor.rowcount


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        if USE_POSTGRES:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Return a wrapper that provides both connection and cursor-like interface
            class PostgresConnection:
                def __init__(self, conn, cursor):
                    self._conn = conn
                    self._cursor = PostgresCursorWrapper(cursor, conn)

                def cursor(self):
                    return self._cursor

                def execute(self, *args, **kwargs):
                    return self._cursor.execute(*args, **kwargs)

                def commit(self):
                    return self._conn.commit()

                def rollback(self):
                    return self._conn.rollback()

            yield PostgresConnection(conn, cursor)
        else:
            yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Designation-based revenue targets (in Lakhs)
DESIGNATION_TARGETS = {
    'Assistant Director': 30.0,
    'Dy. Director': 50.0,
    'Deputy Director': 50.0,
    'Director-II': 60.0,
    'Director-I': 70.0,
    'Director': 60.0,  # Default for unspecified Director level
}

DEFAULT_TARGET = 60.0  # Default if designation not found


def get_target_for_designation(designation: str) -> float:
    """Get annual target based on designation."""
    if not designation:
        return DEFAULT_TARGET
    designation = designation.strip()
    for key, target in DESIGNATION_TARGETS.items():
        if key.lower() in designation.lower():
            return target
    return DEFAULT_TARGET


def init_database():
    """Initialize the database with all required tables."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create offices table with target tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS offices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                office_id TEXT UNIQUE NOT NULL,
                office_name TEXT NOT NULL,
                officer_count INTEGER DEFAULT 0,
                annual_target_per_officer REAL DEFAULT 60.0,
                annual_revenue_target REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create officers table with designation-based targets
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS officers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                designation TEXT,
                discipline TEXT,
                office_id TEXT NOT NULL,
                admin_role_id TEXT,
                password_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                annual_target REAL DEFAULT 60.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (office_id) REFERENCES offices(office_id)
            )
        """)

        # Create assignments table with enhanced financial tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_no TEXT UNIQUE NOT NULL,
                type TEXT CHECK(type IN ('ASSIGNMENT', 'TRAINING', NULL)),
                title TEXT NOT NULL,

                -- Common fields
                client TEXT,
                client_type TEXT,
                city TEXT,
                domain TEXT,
                sub_domain TEXT,
                office_id TEXT NOT NULL,
                status TEXT DEFAULT 'Not Started',

                -- Assignment-specific fields
                tor_scope TEXT,
                work_order_date DATE,
                start_date DATE,
                target_date DATE,
                team_leader_officer_id TEXT,

                -- Training-specific fields
                venue TEXT,
                duration_start DATE,
                duration_end DATE,
                duration_days INTEGER,
                type_of_participants TEXT,
                faculty1_officer_id TEXT,
                faculty2_officer_id TEXT,

                -- Financial fields (without GST)
                total_value REAL DEFAULT 0,
                gross_value REAL DEFAULT 0,

                -- Invoice tracking
                invoice_raised_amount REAL DEFAULT 0,
                invoice_raised_date DATE,

                -- Payment tracking
                payment_received_amount REAL DEFAULT 0,
                payment_received_date DATE,

                -- Revenue shared
                revenue_shared_amount REAL DEFAULT 0,

                -- Legacy fields for compatibility
                invoice_amount REAL DEFAULT 0,
                amount_received REAL DEFAULT 0,
                expected_revenue REAL DEFAULT 0,
                total_revenue REAL DEFAULT 0,
                net_revenue REAL DEFAULT 0,

                -- Total Expenditure (computed from expenditure_items)
                total_expenditure REAL DEFAULT 0,
                surplus_deficit REAL DEFAULT 0,

                -- Progress tracking
                physical_progress_percent REAL DEFAULT 0,
                financial_progress_percent REAL DEFAULT 0,
                timeline_progress_percent REAL DEFAULT 0,

                -- Remarks
                remarks TEXT,

                -- Tracking
                details_filled INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                FOREIGN KEY (team_leader_officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (faculty1_officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (faculty2_officer_id) REFERENCES officers(officer_id)
            )
        """)

        # Create milestones table with invoice/payment status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                milestone_no INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                target_date DATE,
                actual_completion_date DATE,

                -- Invoice percentage for this milestone
                invoice_percent REAL DEFAULT 0,
                invoice_amount REAL DEFAULT 0,

                -- Invoice raised status
                invoice_raised INTEGER DEFAULT 0,
                invoice_raised_date DATE,

                -- Payment received status
                payment_received INTEGER DEFAULT 0,
                payment_received_date DATE,

                -- Legacy fields
                revenue_percent REAL DEFAULT 0,
                revenue_amount REAL DEFAULT 0,

                status TEXT DEFAULT 'Pending' CHECK(status IN ('Pending', 'In Progress', 'Completed', 'Delayed', 'Cancelled')),
                remarks TEXT,
                version INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
                UNIQUE(assignment_id, milestone_no)
            )
        """)

        # Create expenditure_heads table (master list)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenditure_heads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                head_code TEXT UNIQUE NOT NULL,
                head_name TEXT NOT NULL,
                description TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Create expenditure_items table (actual expenditure per assignment)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenditure_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                head_id INTEGER NOT NULL,
                estimated_amount REAL DEFAULT 0,
                actual_amount REAL DEFAULT 0,
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
                FOREIGN KEY (head_id) REFERENCES expenditure_heads(id),
                UNIQUE(assignment_id, head_id)
            )
        """)

        # Create revenue_shares table with version history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS revenue_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                officer_id TEXT NOT NULL,
                share_percent REAL NOT NULL DEFAULT 0,
                share_amount REAL NOT NULL DEFAULT 0,
                version INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                UNIQUE(assignment_id, officer_id)
            )
        """)

        # Create version history table for audit trail
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS version_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name TEXT NOT NULL,
                record_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_by TEXT,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create sessions table for authentication
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                officer_id TEXT NOT NULL,
                active_role TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id) ON DELETE CASCADE
            )
        """)

        # Create financial_year_targets table for tracking targets by year
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS financial_year_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                financial_year TEXT NOT NULL,
                office_id TEXT NOT NULL,
                annual_target REAL DEFAULT 0,
                q1_target REAL DEFAULT 0,
                q2_target REAL DEFAULT 0,
                q3_target REAL DEFAULT 0,
                q4_target REAL DEFAULT 0,
                training_target INTEGER DEFAULT 0,
                lecture_target INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                UNIQUE(financial_year, office_id)
            )
        """)

        # Create config_options table for managing dropdowns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                option_value TEXT NOT NULL,
                option_label TEXT,
                parent_value TEXT,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, option_value)
            )
        """)

        # Insert default configuration options
        _insert_default_config_options(cursor)

        # Create approval_requests table for workflow management
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT NOT NULL,
                -- Types: ASSIGNMENT_APPROVAL, MILESTONE_APPROVAL, REVENUE_SHARE_CHANGE,
                --        TEAM_LEADER_ALLOCATION, ESCALATION
                reference_type TEXT NOT NULL,
                -- Reference types: assignment, milestone, revenue_share
                reference_id INTEGER NOT NULL,
                requested_by TEXT NOT NULL,
                requested_to TEXT,
                -- NULL means goes to office head
                office_id TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                -- Status: PENDING, APPROVED, REJECTED, ESCALATED
                request_data TEXT,
                -- JSON data for the request details
                remarks TEXT,
                approval_remarks TEXT,
                approved_by TEXT,
                approved_at TIMESTAMP,
                escalated_to TEXT,
                escalated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (requested_by) REFERENCES officers(officer_id),
                FOREIGN KEY (approved_by) REFERENCES officers(officer_id),
                FOREIGN KEY (office_id) REFERENCES offices(office_id)
            )
        """)

        # Create assignment_team table for team member assignments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignment_team (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                officer_id TEXT NOT NULL,
                role TEXT DEFAULT 'MEMBER',
                -- Roles: TEAM_LEADER, MEMBER, CONSULTANT
                assigned_by TEXT,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                UNIQUE(assignment_id, officer_id)
            )
        """)

        # Create activity_log table for audit trail
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                -- Actions: CREATE, UPDATE, DELETE, APPROVE, REJECT, ESCALATE, COMMENT
                entity_type TEXT NOT NULL,
                -- Entity types: assignment, milestone, revenue_share, request
                entity_id INTEGER,
                old_data TEXT,
                new_data TEXT,
                remarks TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (actor_id) REFERENCES officers(officer_id)
            )
        """)

        # Add approval_status to assignments if not exists
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN approval_status TEXT DEFAULT 'DRAFT'")
        except:
            pass  # Column already exists

        # Add approval_status to milestones if not exists
        try:
            cursor.execute("ALTER TABLE milestones ADD COLUMN approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass  # Column already exists

        # ============================================================
        # Assignment Workflow Approval Columns
        # ============================================================

        # Cost Estimation Approval
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN cost_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN cost_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN cost_approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN cost_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN cost_submitted_at TIMESTAMP")
        except:
            pass

        # Team Constitution Approval
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN team_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN team_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN team_approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN team_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN team_submitted_at TIMESTAMP")
        except:
            pass

        # Milestone Planning Approval
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN milestone_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN milestone_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN milestone_approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN milestone_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN milestone_submitted_at TIMESTAMP")
        except:
            pass

        # Revenue Share Approval
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN revenue_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN revenue_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN revenue_approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN revenue_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN revenue_submitted_at TIMESTAMP")
        except:
            pass

        # Add Finance verification columns to invoice_requests
        try:
            cursor.execute("ALTER TABLE invoice_requests ADD COLUMN finance_verified_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE invoice_requests ADD COLUMN finance_verified_at TIMESTAMP")
        except:
            pass

        # Create officer_roles table for multiple roles per officer
        # No UNIQUE constraint - allows tracking history of same role assignments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS officer_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT NOT NULL,
                role_type TEXT NOT NULL,
                -- Role types: DG, DDG-I, DDG-II, RD_HEAD, GROUP_HEAD, TEAM_LEADER, ADMIN
                scope_type TEXT,
                -- Scope types: GLOBAL, OFFICE, GROUP
                scope_value TEXT,
                -- For GROUP_HEAD: group name (IE, HRM, Finance, etc.)
                -- For RD_HEAD: office_id (CHN, HYD, etc.)
                is_primary INTEGER DEFAULT 0,
                effective_from DATE DEFAULT CURRENT_DATE,
                effective_to DATE,
                -- NULL means currently active
                order_reference TEXT,
                -- Reference to administrative order
                assigned_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id)
            )
        """)

        # Create reporting_hierarchy table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reporting_hierarchy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                -- Entity types: OFFICE, GROUP
                entity_value TEXT NOT NULL,
                -- For OFFICE: office_id; For GROUP: group name
                reports_to_role TEXT NOT NULL,
                -- DDG-I, DDG-II
                effective_from DATE DEFAULT CURRENT_DATE,
                effective_to DATE,
                updated_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_type, entity_value)
            )
        """)

        # Create groups table for defining groups
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_code TEXT UNIQUE NOT NULL,
                group_name TEXT NOT NULL,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Insert default groups
        _insert_default_groups(cursor)

        # Insert default reporting hierarchy
        _insert_default_reporting_hierarchy(cursor)

        # Create officer_history table for tracking all changes (promotions, transfers, role changes)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS officer_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                -- Change types: DESIGNATION, OFFICE_TRANSFER, ROLE_ASSIGN, ROLE_REMOVE
                field_name TEXT,
                -- Field that changed: designation, office_id, admin_role_id, etc.
                old_value TEXT,
                new_value TEXT,
                effective_from DATE NOT NULL,
                effective_to DATE,
                -- NULL means current/active
                order_reference TEXT,
                -- Reference to administrative order (optional)
                remarks TEXT,
                changed_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id)
            )
        """)

        # Create designation_history table specifically for promotions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS designation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT NOT NULL,
                designation TEXT NOT NULL,
                pay_level TEXT,
                effective_from DATE NOT NULL,
                effective_to DATE,
                promotion_order_no TEXT,
                promotion_order_date DATE,
                remarks TEXT,
                updated_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id)
            )
        """)

        # Create office_transfer_history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS office_transfer_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT NOT NULL,
                from_office_id TEXT,
                to_office_id TEXT NOT NULL,
                effective_from DATE NOT NULL,
                effective_to DATE,
                transfer_order_no TEXT,
                transfer_order_date DATE,
                transfer_type TEXT DEFAULT 'TRANSFER',
                -- Types: INITIAL, TRANSFER, DEPUTATION, REPATRIATION
                remarks TEXT,
                updated_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (from_office_id) REFERENCES offices(office_id),
                FOREIGN KEY (to_office_id) REFERENCES offices(office_id)
            )
        """)

        # Create indexes for history tables
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_officer_history_officer ON officer_history(officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_officer_history_type ON officer_history(change_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_designation_history_officer ON designation_history(officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_office_transfer_officer ON office_transfer_history(officer_id)")

        # ============================================================
        # PHASE-1 UPGRADE: 4-Stage Assignment Workflow Tables
        # ============================================================

        # Enquiry Stage (Stage 1 of 4-stage workflow)
        # Workflow: Created by any officer → Pending Head approval → Allocated to officer → Progress updates → Convert to PR
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enquiry_number TEXT UNIQUE NOT NULL,
                client_name TEXT NOT NULL,
                client_type TEXT,
                domain TEXT,
                sub_domain TEXT,
                office_id TEXT NOT NULL,
                officer_id TEXT,
                -- Allocated officer (assigned by Head)
                description TEXT,
                estimated_value REAL,
                target_date DATE,
                status TEXT DEFAULT 'PENDING_APPROVAL',
                -- Status: PENDING_APPROVAL, APPROVED, IN_PROGRESS, ON_HOLD, CONVERTED_TO_PR, DROPPED, REJECTED
                approval_status TEXT DEFAULT 'PENDING',
                -- PENDING, APPROVED, REJECTED
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                current_update TEXT,
                -- Latest progress update by officer
                drop_reason TEXT,
                remarks TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id),
                FOREIGN KEY (approved_by) REFERENCES officers(officer_id)
            )
        """)

        # Non-Revenue Suggestions Table (Stage 1 of Non-Revenue workflow)
        # Workflow: Suggestion → PR → Proposal → Execution
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS non_revenue_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_number TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                activity_type TEXT,
                -- Type: CAPACITY_BUILDING, KNOWLEDGE_SHARING, INTERNAL_PROJECT, RESEARCH, OTHER
                beneficiary TEXT,
                -- Who benefits from this activity
                domain TEXT,
                office_id TEXT NOT NULL,
                officer_id TEXT,
                -- Allocated officer
                justification TEXT,
                -- Why this is important
                expected_outcome TEXT,
                notional_value REAL DEFAULT 0,
                -- Estimated notional value
                target_start_date DATE,
                target_end_date DATE,
                status TEXT DEFAULT 'PENDING_APPROVAL',
                -- PENDING_APPROVAL, APPROVED, IN_PROGRESS, ON_HOLD, CONVERTED_TO_PR, COMPLETED, DROPPED, REJECTED
                approval_status TEXT DEFAULT 'PENDING',
                -- PENDING, APPROVED, REJECTED
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                current_update TEXT,
                drop_reason TEXT,
                remarks TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id),
                FOREIGN KEY (approved_by) REFERENCES officers(officer_id)
            )
        """)

        # Proposal Request Stage (Stage 2 of 4-stage workflow)
        # Same approval workflow as enquiries
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proposal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_number TEXT UNIQUE NOT NULL,
                enquiry_id INTEGER,
                -- Can be NULL for direct PR without enquiry
                client_name TEXT NOT NULL,
                client_type TEXT,
                domain TEXT,
                sub_domain TEXT,
                office_id TEXT NOT NULL,
                officer_id TEXT,
                -- Allocated officer
                description TEXT,
                estimated_value REAL,
                target_date DATE,
                -- Target: Date by which proposal should be submitted
                status TEXT DEFAULT 'PENDING_APPROVAL',
                -- Status: PENDING_APPROVAL, APPROVED, IN_PROGRESS, CONVERTED_TO_PROPOSAL, ON_HOLD, DROPPED, REJECTED
                approval_status TEXT DEFAULT 'PENDING',
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                current_update TEXT,
                drop_reason TEXT,
                remarks TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (enquiry_id) REFERENCES enquiries(id),
                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id),
                FOREIGN KEY (approved_by) REFERENCES officers(officer_id)
            )
        """)

        # Proposal Stage (Stage 3 of 4-stage workflow)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_number TEXT UNIQUE NOT NULL,
                pr_id INTEGER,
                enquiry_id INTEGER,
                -- Can be NULL for direct proposal
                client_name TEXT NOT NULL,
                client_type TEXT,
                domain TEXT,
                sub_domain TEXT,
                office_id TEXT NOT NULL,
                officer_id TEXT,
                -- Allocated officer
                description TEXT,
                estimated_value REAL,
                -- Initial estimated value
                proposed_value REAL,
                -- Value proposed to client
                work_order_value REAL,
                -- Final WO value if won
                submission_date DATE,
                target_date DATE,
                -- Target: Expected date of work order
                validity_date DATE,
                -- Proposal validity
                status TEXT DEFAULT 'PENDING_APPROVAL',
                -- Status: PENDING_APPROVAL, APPROVED, IN_PROGRESS, SUBMITTED, UNDER_REVIEW, SHORTLISTED, WON, LOST, WITHDRAWN, ON_HOLD, DROPPED, REJECTED
                approval_status TEXT DEFAULT 'PENDING',
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                current_update TEXT,
                drop_reason TEXT,
                loss_reason TEXT,
                withdraw_reason TEXT,
                remarks TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pr_id) REFERENCES proposal_requests(id),
                FOREIGN KEY (enquiry_id) REFERENCES enquiries(id),
                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id)
            )
        """)

        # Add approval workflow columns to enquiries table (for existing databases)
        try:
            cursor.execute("ALTER TABLE enquiries ADD COLUMN approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE enquiries ADD COLUMN approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE enquiries ADD COLUMN approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE enquiries ADD COLUMN rejection_reason TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE enquiries ADD COLUMN current_update TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE enquiries ADD COLUMN drop_reason TEXT")
        except:
            pass

        # Add approval workflow columns to proposal_requests table (for existing databases)
        try:
            cursor.execute("ALTER TABLE proposal_requests ADD COLUMN approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposal_requests ADD COLUMN approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposal_requests ADD COLUMN approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposal_requests ADD COLUMN rejection_reason TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposal_requests ADD COLUMN current_update TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposal_requests ADD COLUMN drop_reason TEXT")
        except:
            pass

        # Add approval workflow columns to proposals table (for existing databases)
        try:
            cursor.execute("ALTER TABLE proposals ADD COLUMN approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposals ADD COLUMN approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposals ADD COLUMN approved_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposals ADD COLUMN rejection_reason TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposals ADD COLUMN current_update TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE proposals ADD COLUMN drop_reason TEXT")
        except:
            pass

        # Link assignments to proposal chain (Stage 4 = Work Order/Assignment)
        # Add columns to existing assignments table
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN proposal_id INTEGER REFERENCES proposals(id)")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN enquiry_id INTEGER REFERENCES enquiries(id)")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE assignments ADD COLUMN workflow_stage TEXT DEFAULT 'WORK_ORDER'")
        except:
            pass

        # ============================================================
        # PHASE-1 UPGRADE: 80-20 Revenue Recognition Model
        # ============================================================

        # Invoice Requests (for 80% recognition)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoice_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_number TEXT UNIQUE NOT NULL,
                assignment_id INTEGER NOT NULL,
                milestone_id INTEGER,
                invoice_type TEXT DEFAULT 'SUBSEQUENT',
                -- Types: ADVANCE, SUBSEQUENT, FINAL
                invoice_amount REAL NOT NULL,
                fy_period TEXT NOT NULL,
                -- Financial year: 2024-25, 2025-26, etc.
                description TEXT,
                status TEXT DEFAULT 'PENDING',
                -- Status: PENDING, APPROVED, REJECTED, INVOICED
                requested_by TEXT NOT NULL,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_by TEXT,
                verified_at TIMESTAMP,
                verification_remarks TEXT,
                approved_by TEXT,
                approved_at TIMESTAMP,
                approval_remarks TEXT,
                tally_voucher_ref TEXT,
                tally_cost_centre TEXT,
                tally_invoice_date DATE,
                revenue_recognized_80 REAL DEFAULT 0,
                -- 80% of invoice amount
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                FOREIGN KEY (milestone_id) REFERENCES milestones(id),
                FOREIGN KEY (requested_by) REFERENCES officers(officer_id),
                FOREIGN KEY (verified_by) REFERENCES officers(officer_id),
                FOREIGN KEY (approved_by) REFERENCES officers(officer_id)
            )
        """)

        # Payment Receipts (for remaining 20% recognition)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_number TEXT UNIQUE NOT NULL,
                invoice_request_id INTEGER NOT NULL,
                amount_received REAL NOT NULL,
                receipt_date DATE NOT NULL,
                payment_mode TEXT,
                -- NEFT, RTGS, CHEQUE, DD, CASH
                reference_number TEXT,
                -- UTR/Cheque/DD number
                fy_period TEXT NOT NULL,
                remarks TEXT,
                revenue_recognized_20 REAL DEFAULT 0,
                -- 20% auto-allocated
                updated_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (invoice_request_id) REFERENCES invoice_requests(id),
                FOREIGN KEY (updated_by) REFERENCES officers(officer_id)
            )
        """)

        # Officer Revenue Ledger (detailed 80-20 tracking per officer)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS officer_revenue_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT NOT NULL,
                assignment_id INTEGER NOT NULL,
                invoice_request_id INTEGER,
                payment_receipt_id INTEGER,
                revenue_type TEXT NOT NULL,
                -- Types: INVOICE_80, PAYMENT_20
                share_percent REAL NOT NULL,
                amount REAL NOT NULL,
                fy_period TEXT NOT NULL,
                transaction_date DATE NOT NULL,
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                FOREIGN KEY (invoice_request_id) REFERENCES invoice_requests(id),
                FOREIGN KEY (payment_receipt_id) REFERENCES payment_receipts(id)
            )
        """)

        # ============================================================
        # PHASE-1 UPGRADE: Officer Grievance & Escalation System
        # ============================================================

        # Grievance Tickets
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grievance_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_number TEXT UNIQUE NOT NULL,
                officer_id TEXT NOT NULL,
                assignment_id INTEGER,
                -- Can be NULL for general grievances
                complaint_type TEXT NOT NULL,
                -- Types: ALLOCATION_PERCENT, COST_ESTIMATE, REVENUE_SHARE,
                --        MILESTONE_DATE, DATA_INCONSISTENCY, OTHER
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'OPEN',
                -- Status: OPEN, IN_PROGRESS, ESCALATED, RESOLVED, CLOSED
                priority TEXT DEFAULT 'NORMAL',
                -- Priority: LOW, NORMAL, HIGH, URGENT
                current_level TEXT DEFAULT 'TL',
                -- Escalation level: TL, HEAD, DDG, DG
                assigned_to TEXT,
                -- Current handler
                resolution TEXT,
                resolution_date DATE,
                escalation_due_date DATE,
                -- Auto-escalation date
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                FOREIGN KEY (assigned_to) REFERENCES officers(officer_id)
            )
        """)

        # Grievance Responses/Comments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grievance_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                responder_id TEXT NOT NULL,
                response_type TEXT DEFAULT 'COMMENT',
                -- Types: COMMENT, ACTION_TAKEN, ESCALATION, RESOLUTION
                response_text TEXT NOT NULL,
                attachments TEXT,
                -- JSON array of file paths
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES grievance_tickets(id),
                FOREIGN KEY (responder_id) REFERENCES officers(officer_id)
            )
        """)

        # Grievance Escalation History
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grievance_escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                from_level TEXT NOT NULL,
                to_level TEXT NOT NULL,
                from_handler TEXT,
                to_handler TEXT,
                escalation_reason TEXT,
                auto_escalated INTEGER DEFAULT 0,
                -- 1 if auto-escalated due to timeline
                escalated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES grievance_tickets(id),
                FOREIGN KEY (from_handler) REFERENCES officers(officer_id),
                FOREIGN KEY (to_handler) REFERENCES officers(officer_id)
            )
        """)

        # ============================================================
        # PHASE-1 UPGRADE: Training Module (5-Stage Lifecycle)
        # ============================================================

        # Training Programmes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_programmes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                programme_number TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                topic_domain TEXT,
                description TEXT,
                training_start_date DATE,
                training_end_date DATE,
                duration_days INTEGER,
                location TEXT,
                venue_details TEXT,
                mode TEXT DEFAULT 'IN_PERSON',
                -- Modes: IN_PERSON, ONLINE, HYBRID
                office_id TEXT NOT NULL,

                -- Budgeted values
                budgeted_participants INTEGER DEFAULT 0,
                fee_per_participant REAL DEFAULT 0,
                budgeted_revenue REAL DEFAULT 0,

                -- Actual values (updated as programme progresses)
                actual_registered INTEGER DEFAULT 0,
                actual_attended INTEGER DEFAULT 0,
                actual_revenue REAL DEFAULT 0,

                -- Application window
                application_start_date DATE,
                application_end_date DATE,

                -- Stage tracking
                stage TEXT DEFAULT 'ANNOUNCED',
                -- Stages: ANNOUNCED, REGISTRATION_OPEN, REGISTRATION_CLOSED,
                --         CONDUCTED, INVOICED, CLOSED

                -- Financial tracking
                invoice_raised INTEGER DEFAULT 0,
                invoice_date DATE,
                payment_received INTEGER DEFAULT 0,
                payment_date DATE,

                -- Certificate tracking
                certificates_issued INTEGER DEFAULT 0,

                remarks TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (office_id) REFERENCES offices(office_id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id)
            )
        """)

        # Trainer Allocations (multiple trainers per programme)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trainer_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                programme_id INTEGER NOT NULL,
                officer_id TEXT NOT NULL,
                trainer_role TEXT DEFAULT 'CO_TRAINER',
                -- Roles: PRIMARY, CO_TRAINER, COORDINATOR, GUEST_FACULTY
                allocation_percent REAL NOT NULL DEFAULT 0,
                training_days REAL DEFAULT 0,
                -- Days this trainer will deliver
                accepted INTEGER DEFAULT 0,
                -- 1 if trainer accepted
                accepted_at TIMESTAMP,
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (programme_id) REFERENCES training_programmes(id),
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                UNIQUE(programme_id, officer_id)
            )
        """)

        # Training Participants
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                programme_id INTEGER NOT NULL,
                participant_name TEXT NOT NULL,
                organization TEXT,
                designation TEXT,
                email TEXT,
                phone TEXT,
                application_date DATE,
                status TEXT DEFAULT 'APPLIED',
                -- Status: APPLIED, APPROVED, WAITLIST, REJECTED, CONFIRMED, ATTENDED, NO_SHOW
                attendance_status TEXT,
                -- PRESENT, ABSENT, PARTIAL
                certificate_issued INTEGER DEFAULT 0,
                certificate_date DATE,
                fee_paid REAL DEFAULT 0,
                payment_status TEXT DEFAULT 'PENDING',
                -- PENDING, PARTIAL, PAID
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (programme_id) REFERENCES training_programmes(id)
            )
        """)

        # Training Revenue Ledger (similar to officer_revenue_ledger but for training)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_revenue_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT NOT NULL,
                programme_id INTEGER NOT NULL,
                revenue_type TEXT NOT NULL,
                -- Types: INVOICE_80, PAYMENT_20
                share_percent REAL NOT NULL,
                amount REAL NOT NULL,
                fy_period TEXT NOT NULL,
                transaction_date DATE NOT NULL,
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
                FOREIGN KEY (programme_id) REFERENCES training_programmes(id)
            )
        """)

        # ============================================================
        # Training Programme Approval Workflow Columns
        # ============================================================

        # Coordinator assignment (similar to TL for assignments)
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN coordinator_id TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN approval_status TEXT DEFAULT 'DRAFT'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN approved_at TIMESTAMP")
        except:
            pass

        # Budget/Cost Approval
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN budget_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN budget_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN budget_submitted_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN budget_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN budget_approved_at TIMESTAMP")
        except:
            pass

        # Trainer Allocation Approval
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN trainer_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN trainer_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN trainer_submitted_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN trainer_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN trainer_approved_at TIMESTAMP")
        except:
            pass

        # Revenue Share Approval
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN revenue_approval_status TEXT DEFAULT 'PENDING'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN revenue_submitted_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN revenue_submitted_at TIMESTAMP")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN revenue_approved_by TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE training_programmes ADD COLUMN revenue_approved_at TIMESTAMP")
        except:
            pass

        # ============================================================
        # PHASE-1 UPGRADE: Cost Estimate Versioning
        # ============================================================

        # Cost Estimate Versions (for audit trail)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cost_estimate_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                total_estimated REAL DEFAULT 0,
                change_reason TEXT,
                -- Mandatory reason for changes
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id),
                UNIQUE(assignment_id, version_number)
            )
        """)

        # Cost Estimate Version Details (per expenditure head)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cost_estimate_version_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                head_id INTEGER NOT NULL,
                estimated_amount REAL DEFAULT 0,
                FOREIGN KEY (version_id) REFERENCES cost_estimate_versions(id),
                FOREIGN KEY (head_id) REFERENCES expenditure_heads(id)
            )
        """)

        # ============================================================
        # PHASE-1 UPGRADE: Milestone Versioning
        # ============================================================

        # Milestone Plan Versions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS milestone_plan_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                total_milestones INTEGER DEFAULT 0,
                change_reason TEXT,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                FOREIGN KEY (created_by) REFERENCES officers(officer_id),
                UNIQUE(assignment_id, version_number)
            )
        """)

        # ============================================================
        # Indexes for new tables
        # ============================================================

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enquiries_office ON enquiries(office_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enquiries_status ON enquiries(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposal_requests_enquiry ON proposal_requests(enquiry_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_pr ON proposals(pr_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoice_requests_assignment ON invoice_requests(assignment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoice_requests_status ON invoice_requests(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_receipts_invoice ON payment_receipts(invoice_request_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_officer_revenue_ledger_officer ON officer_revenue_ledger(officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_officer_revenue_ledger_assignment ON officer_revenue_ledger(assignment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grievance_tickets_officer ON grievance_tickets(officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grievance_tickets_status ON grievance_tickets(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_training_programmes_office ON training_programmes(office_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_training_programmes_stage ON training_programmes(stage)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trainer_allocations_programme ON trainer_allocations(programme_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trainer_allocations_officer ON trainer_allocations(officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_training_participants_programme ON training_participants(programme_id)")

        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assignments_office ON assignments(office_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assignments_type ON assignments(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assignments_progress ON assignments(physical_progress_percent)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assignments_timeline ON assignments(timeline_progress_percent)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_revenue_shares_assignment ON revenue_shares(assignment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_revenue_shares_officer ON revenue_shares(officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_officers_office ON officers(office_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_officers_designation ON officers(designation)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_milestones_assignment ON milestones(assignment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenditure_items_assignment ON expenditure_items(assignment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_history ON version_history(table_name, record_id)")

        # Insert default expenditure heads based on CMR format
        _insert_default_expenditure_heads(cursor)

        # Create default admin user
        _create_admin_user(cursor)

        print("Database initialized successfully!")


def _insert_default_expenditure_heads(cursor):
    """Insert default expenditure heads from CMR format."""
    heads = [
        # A. Consultant Fee
        ('A', 'A1', 'NPC Consultant Fee', 'NPC Consultant days x rate'),
        ('A', 'A2', 'Guest Consultant Fee', 'Guest Consultant days x rate'),
        ('A', 'A3', 'Faculty Fee', 'Faculty days x rate'),
        ('A', 'A4', 'Project Associate Fee', 'Project Associate days x rate'),
        ('A', 'A5', 'Support Staff Fee', 'Support Staff days x rate'),

        # B. Travel Expenses
        ('B', 'B1', 'NPC Consultant Travel', 'Travel expenses for NPC consultants'),
        ('B', 'B2', 'NPC Supporting Staff Travel', 'Travel expenses for supporting staff'),
        ('B', 'B3', 'Guest Consultant Travel', 'Travel expenses for guest consultants'),
        ('B', 'B4', 'Local Conveyance', 'Local conveyance for all consultants'),

        # C. Lodge & Board
        ('C', 'C1', 'Outstation NPC Consultant Stay', 'Lodge & board for outstation NPC consultants'),
        ('C', 'C2', 'Local NPC Consultant Expenses', 'Expenses for local NPC consultants'),
        ('C', 'C3', 'Guest Faculty Stay', 'Lodge & board for guest faculty'),
        ('C', 'C4', 'Project Associate Stay', 'Lodge & board for project associates'),

        # D. Publication Charges
        ('D', 'D1', 'Publication Titles', 'Cost of publication titles'),
        ('D', 'D2', 'Periodicals', 'Cost of periodicals'),
        ('D', 'D3', 'Printing & Binding', 'Printing and binding charges'),

        # E. Administrative Expenses
        ('E', 'E1', 'Hall Hiring', 'Cost of hiring hall/venue'),
        ('E', 'E2', 'Refreshment', 'Refreshment expenses'),
        ('E', 'E3', 'Working Lunch', 'Working lunch expenses'),
        ('E', 'E4', 'Advertisement', 'Advertisement charges'),
        ('E', 'E5', 'Brochure', 'Brochure printing costs'),
        ('E', 'E6', 'Stationery', 'Stationery expenses'),
        ('E', 'E7', 'Cyclostyled Material', 'Cyclostyling charges'),
        ('E', 'E8', 'Training Aids', 'Training aids and materials'),
        ('E', 'E9', 'Residential Expenses', 'Residential expenses for participants'),
        ('E', 'E10', 'Factory/Site Visits', 'Factory or site visit expenses'),
        ('E', 'E11', 'Documentation Fees', 'Documentation fees'),
        ('E', 'E12', 'IT/Dashboard Design', 'IT dashboard design costs'),
        ('E', 'E13', 'Miscellaneous', 'Other miscellaneous expenses'),

        # F. Contingency
        ('F', 'F1', 'Unforeseen Expenses', '5% towards unforeseen expenses'),
    ]

    for category, code, name, desc in heads:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO expenditure_heads (category, head_code, head_name, description)
                VALUES (?, ?, ?, ?)
            """, (category, code, name, desc))
        except Exception:
            pass


def _insert_default_config_options(cursor):
    """Insert default configuration options for domains, sub-domains, client types, etc."""
    options = [
        # Domains
        ('domain', 'ES', 'Economic Services', None, 1),
        ('domain', 'IE', 'Industrial Engineering', None, 2),
        ('domain', 'HRM', 'Human Resource Management', None, 3),
        ('domain', 'IT', 'Information Technology', None, 4),
        ('domain', 'Agri', 'Agri-Business', None, 5),
        ('domain', 'TM', 'Training & Management', None, 6),
        ('domain', 'General', 'General', None, 7),

        # Sub-domains for ES (Economic Services)
        ('sub_domain', 'ES-Eval', 'Evaluation Studies', 'ES', 1),
        ('sub_domain', 'ES-Impact', 'Impact Assessment', 'ES', 2),
        ('sub_domain', 'ES-Policy', 'Policy Analysis', 'ES', 3),
        ('sub_domain', 'ES-Trade', 'Trade & Commerce', 'ES', 4),
        ('sub_domain', 'ES-Infra', 'Infrastructure', 'ES', 5),

        # Sub-domains for IE (Industrial Engineering)
        ('sub_domain', 'IE-Process', 'Process Optimization', 'IE', 1),
        ('sub_domain', 'IE-Quality', 'Quality Management', 'IE', 2),
        ('sub_domain', 'IE-Lean', 'Lean Manufacturing', 'IE', 3),
        ('sub_domain', 'IE-Energy', 'Energy Management', 'IE', 4),
        ('sub_domain', 'IE-Prod', 'Productivity Improvement', 'IE', 5),

        # Sub-domains for HRM
        ('sub_domain', 'HRM-OD', 'Organizational Development', 'HRM', 1),
        ('sub_domain', 'HRM-TNA', 'Training Need Assessment', 'HRM', 2),
        ('sub_domain', 'HRM-PMS', 'Performance Management', 'HRM', 3),
        ('sub_domain', 'HRM-Comp', 'Competency Mapping', 'HRM', 4),
        ('sub_domain', 'HRM-MP', 'Manpower Planning', 'HRM', 5),

        # Sub-domains for IT
        ('sub_domain', 'IT-Digital', 'Digital Transformation', 'IT', 1),
        ('sub_domain', 'IT-Data', 'Data Analytics', 'IT', 2),
        ('sub_domain', 'IT-ERP', 'ERP Implementation', 'IT', 3),
        ('sub_domain', 'IT-Cyber', 'Cybersecurity', 'IT', 4),
        ('sub_domain', 'IT-Infra', 'IT Infrastructure', 'IT', 5),

        # Sub-domains for Agri
        ('sub_domain', 'Agri-Supply', 'Supply Chain', 'Agri', 1),
        ('sub_domain', 'Agri-Prod', 'Farm Productivity', 'Agri', 2),
        ('sub_domain', 'Agri-Food', 'Food Processing', 'Agri', 3),
        ('sub_domain', 'Agri-Biz', 'Agri-Business Development', 'Agri', 4),

        # Sub-domains for TM (Training & Management)
        ('sub_domain', 'TM-MDP', 'Management Development', 'TM', 1),
        ('sub_domain', 'TM-EDP', 'Executive Development', 'TM', 2),
        ('sub_domain', 'TM-Lead', 'Leadership Programs', 'TM', 3),
        ('sub_domain', 'TM-Skill', 'Skill Development', 'TM', 4),

        # Sub-domains for General
        ('sub_domain', 'Gen-Strategy', 'Strategic Planning', 'General', 1),
        ('sub_domain', 'Gen-Advisory', 'Advisory Services', 'General', 2),
        ('sub_domain', 'Gen-Capacity', 'Capacity Building', 'General', 3),

        # Client Types
        ('client_type', 'Central Government', 'Central Government', None, 1),
        ('client_type', 'State Government', 'State Government', None, 2),
        ('client_type', 'PSU', 'Public Sector Undertaking', None, 3),
        ('client_type', 'Private', 'Private Sector', None, 4),
        ('client_type', 'International', 'International Organization', None, 5),
        ('client_type', 'Others', 'Others', None, 6),

        # Assignment Status
        ('status', 'Pipeline', 'Pipeline', None, 1),
        ('status', 'Not Started', 'Not Started', None, 2),
        ('status', 'Ongoing', 'Ongoing', None, 3),
        ('status', 'Completed', 'Completed', None, 4),
        ('status', 'On Hold', 'On Hold', None, 5),
        ('status', 'Cancelled', 'Cancelled', None, 6),
    ]

    for category, value, label, parent, sort_order in options:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO config_options
                (category, option_value, option_label, parent_value, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (category, value, label, parent, sort_order))
        except Exception:
            pass


def _insert_default_groups(cursor):
    """Insert default groups."""
    groups = [
        ('IE', 'Industrial Engineering', 'Industrial Engineering Group'),
        ('AB', 'Agri-Business', 'Agri-Business Group'),
        ('ES', 'Economic Services', 'Economic Services Group'),
        ('IT', 'Information Technology', 'Information Technology Group'),
        ('Admin', 'Administration', 'Administration Group'),
        ('ECA', 'Economic & Cost Analysis', 'Economic & Cost Analysis Group'),
        ('EM', 'Energy Management', 'Energy Management Group'),
        ('IS', 'International Services', 'International Services Group'),
        ('Finance', 'Finance', 'Finance Group'),
        ('HRM', 'Human Resource Management', 'Human Resource Management Group'),
    ]

    for code, name, desc in groups:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO groups (group_code, group_name, description)
                VALUES (?, ?, ?)
            """, (code, name, desc))
        except Exception:
            pass


def _insert_default_reporting_hierarchy(cursor):
    """Insert default reporting hierarchy."""
    # Groups reporting to DDG-I
    ddg1_groups = ['IE', 'AB', 'ES', 'IT', 'Admin']
    ddg1_offices = ['CHN', 'HYD', 'BLR', 'GNR', 'MUM', 'JAI']

    # Groups reporting to DDG-II
    ddg2_groups = ['ECA', 'EM', 'IS', 'Finance', 'HRM']
    ddg2_offices = ['CHD', 'KNP', 'GUW', 'PAT', 'KOL', 'BBS']

    for group in ddg1_groups:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                VALUES ('GROUP', ?, 'DDG-I')
            """, (group,))
        except Exception:
            pass

    for office in ddg1_offices:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                VALUES ('OFFICE', ?, 'DDG-I')
            """, (office,))
        except Exception:
            pass

    for group in ddg2_groups:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                VALUES ('GROUP', ?, 'DDG-II')
            """, (group,))
        except Exception:
            pass

    for office in ddg2_offices:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                VALUES ('OFFICE', ?, 'DDG-II')
            """, (office,))
        except Exception:
            pass


def _create_admin_user(cursor):
    """Create default admin user if not exists."""
    import bcrypt

    # Check if admin user already exists
    cursor.execute("SELECT officer_id FROM officers WHERE officer_id = 'ADMIN'")
    if cursor.fetchone():
        return  # Admin already exists

    # Create HQ office if not exists
    cursor.execute("""
        INSERT OR IGNORE INTO offices (office_id, office_name)
        VALUES ('HQ', 'Head Quarters')
    """)

    # Default admin password - should be changed after first login
    default_password = "Admin@NPC2024"
    password_hash = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Create admin user
    cursor.execute("""
        INSERT OR IGNORE INTO officers
        (officer_id, name, email, designation, office_id, admin_role_id, password_hash, is_active, annual_target)
        VALUES ('ADMIN', 'System Administrator', 'admin@npcindia.gov.in', 'System Admin', 'HQ', 'ADMIN', ?, 1, 0)
    """, (password_hash,))

    print("  Created default admin user: ADMIN / Admin@NPC2024")


def calculate_physical_progress(assignment_id: int) -> float:
    """
    Calculate physical progress based on milestones:
    - 100% of invoice value if payment received
    - 80% of invoice value if invoice raised but payment pending
    - 0% if invoice not raised

    Physical Progress = (sum of weighted milestone values) / total assignment value * 100
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Get assignment total value
        cursor.execute("SELECT total_value, gross_value FROM assignments WHERE id = ?", (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            return 0.0

        total_value = assignment['total_value'] or assignment['gross_value'] or 0
        if total_value <= 0:
            return 0.0

        # Get milestones and calculate weighted progress
        cursor.execute("""
            SELECT invoice_percent, invoice_raised, payment_received
            FROM milestones
            WHERE assignment_id = ?
        """, (assignment_id,))

        weighted_sum = 0.0
        for m in cursor.fetchall():
            invoice_pct = m['invoice_percent'] or 0
            if m['payment_received']:
                # 100% if payment received
                weighted_sum += invoice_pct * 1.0
            elif m['invoice_raised']:
                # 80% if invoice raised but payment pending
                weighted_sum += invoice_pct * 0.8
            # 0% if invoice not raised

        return round(weighted_sum, 2)


def calculate_timeline_progress(assignment_id: int) -> float:
    """
    Calculate timeline-based progress:
    - 100% if milestone completed within target date
    - Reduced % based on delay days

    Timeline Progress = weighted average of milestone timeline performance
    """
    from datetime import date

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT milestone_no, target_date, actual_completion_date,
                   invoice_percent, status, invoice_raised
            FROM milestones
            WHERE assignment_id = ?
            ORDER BY milestone_no
        """, (assignment_id,))

        milestones = cursor.fetchall()
        if not milestones:
            return 0.0

        total_weight = 0.0
        weighted_timeline_sum = 0.0
        today = date.today()

        for m in milestones:
            weight = m['invoice_percent'] or 0
            total_weight += weight

            if not m['target_date']:
                continue

            target = date.fromisoformat(m['target_date']) if isinstance(m['target_date'], str) else m['target_date']

            if m['status'] == 'Completed' and m['actual_completion_date']:
                actual = date.fromisoformat(m['actual_completion_date']) if isinstance(m['actual_completion_date'], str) else m['actual_completion_date']

                if actual <= target:
                    # Completed on time - 100%
                    weighted_timeline_sum += weight * 100
                else:
                    # Delayed - reduce by delay percentage
                    delay_days = (actual - target).days
                    total_days = max((target - date(target.year, 4, 1)).days, 30)  # Use FY start or min 30 days
                    delay_pct = min(delay_days / total_days * 100, 50)  # Max 50% reduction
                    weighted_timeline_sum += weight * (100 - delay_pct)
            elif m['invoice_raised'] and target < today:
                # Invoice raised but past target date
                delay_days = (today - target).days
                total_days = max((target - date(target.year, 4, 1)).days, 30)
                delay_pct = min(delay_days / total_days * 100, 50)
                weighted_timeline_sum += weight * (100 - delay_pct)
            elif target >= today:
                # Future milestone - assume on track
                weighted_timeline_sum += weight * 100

        if total_weight <= 0:
            return 0.0

        return round(weighted_timeline_sum / total_weight, 2)


def calculate_shareable_revenue(assignment_id: int) -> float:
    """
    Calculate revenue to be shared:
    - 100% of invoice value (without GST) if payment received
    - 80% of invoice value (without GST) if invoice raised but payment pending
    - 0% if invoice not raised
    """
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT invoice_amount, invoice_raised, payment_received
            FROM milestones
            WHERE assignment_id = ?
        """, (assignment_id,))

        shareable = 0.0
        for m in cursor.fetchall():
            invoice_amt = m['invoice_amount'] or 0
            if m['payment_received']:
                shareable += invoice_amt * 1.0
            elif m['invoice_raised']:
                shareable += invoice_amt * 0.8

        return round(shareable, 2)


def update_assignment_progress(assignment_id: int):
    """Update all progress fields for an assignment."""
    physical_progress = calculate_physical_progress(assignment_id)
    timeline_progress = calculate_timeline_progress(assignment_id)
    shareable_revenue = calculate_shareable_revenue(assignment_id)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE assignments SET
                physical_progress_percent = ?,
                timeline_progress_percent = ?,
                revenue_shared_amount = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (physical_progress, timeline_progress, shareable_revenue, assignment_id))


def reset_database():
    """Drop all tables and reinitialize (for development only)."""
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_database()
    print("Database reset complete!")


# ============================================================
# PHASE-1 UPGRADE: Helper Functions for 4-Stage Workflow
# ============================================================

def generate_enquiry_number(office_id: str) -> str:
    """Generate unique enquiry number: ENQ/OFFICE/YYYY/NNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM enquiries
            WHERE enquiry_number LIKE ?
        """, (f"ENQ/{office_id}/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"ENQ/{office_id}/{year}/{next_num:04d}"


def generate_pr_number(office_id: str) -> str:
    """Generate unique proposal request number: PR/OFFICE/YYYY/NNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM proposal_requests
            WHERE pr_number LIKE ?
        """, (f"PR/{office_id}/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"PR/{office_id}/{year}/{next_num:04d}"


def generate_suggestion_number(office_id: str) -> str:
    """Generate unique non-revenue suggestion number: NRS/OFFICE/YYYY/NNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM non_revenue_suggestions
            WHERE suggestion_number LIKE ?
        """, (f"NRS/{office_id}/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"NRS/{office_id}/{year}/{next_num:04d}"


def generate_proposal_number(office_id: str) -> str:
    """Generate unique proposal number: PROP/OFFICE/YYYY/NNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM proposals
            WHERE proposal_number LIKE ?
        """, (f"PROP/{office_id}/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"PROP/{office_id}/{year}/{next_num:04d}"


def generate_invoice_request_number() -> str:
    """Generate unique invoice request number: INV-REQ/YYYY/NNNNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM invoice_requests
            WHERE request_number LIKE ?
        """, (f"INV-REQ/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"INV-REQ/{year}/{next_num:06d}"


def generate_grievance_ticket_number() -> str:
    """Generate unique grievance ticket number: GRV/YYYY/NNNNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM grievance_tickets
            WHERE ticket_number LIKE ?
        """, (f"GRV/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"GRV/{year}/{next_num:06d}"


def generate_training_programme_number(office_id: str) -> str:
    """Generate unique training programme number: TRN/OFFICE/YYYY/NNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM training_programmes
            WHERE programme_number LIKE ?
        """, (f"TRN/{office_id}/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"TRN/{office_id}/{year}/{next_num:04d}"


def generate_payment_receipt_number() -> str:
    """Generate unique payment receipt number: RCPT/YYYY/NNNNNN"""
    from datetime import date
    year = date.today().year

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) + 1 as next_num FROM payment_receipts
            WHERE receipt_number LIKE ?
        """, (f"RCPT/{year}/%",))
        next_num = cursor.fetchone()['next_num']

    return f"RCPT/{year}/{next_num:06d}"


# ============================================================
# PHASE-1 UPGRADE: 80-20 Revenue Recognition Functions
# ============================================================

def get_current_fy() -> str:
    """Get current financial year in format: 2024-25"""
    from datetime import date
    today = date.today()
    if today.month >= 4:  # April onwards
        return f"{today.year}-{str(today.year + 1)[2:]}"
    else:  # Jan-Mar belongs to previous FY
        return f"{today.year - 1}-{str(today.year)[2:]}"


def calculate_80_20_revenue(assignment_id: int) -> dict:
    """
    Calculate 80-20 revenue for an assignment.
    Returns dict with invoice_revenue_80, payment_revenue_20, total_recognized
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Get approved invoices (80% recognition)
        cursor.execute("""
            SELECT COALESCE(SUM(revenue_recognized_80), 0) as invoice_80
            FROM invoice_requests
            WHERE assignment_id = ? AND status IN ('APPROVED', 'INVOICED')
        """, (assignment_id,))
        invoice_80 = cursor.fetchone()['invoice_80'] or 0

        # Get payments received (20% recognition)
        cursor.execute("""
            SELECT COALESCE(SUM(pr.revenue_recognized_20), 0) as payment_20
            FROM payment_receipts pr
            JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
            WHERE ir.assignment_id = ?
        """, (assignment_id,))
        payment_20 = cursor.fetchone()['payment_20'] or 0

        return {
            'invoice_revenue_80': round(invoice_80, 2),
            'payment_revenue_20': round(payment_20, 2),
            'total_recognized': round(invoice_80 + payment_20, 2)
        }


def allocate_officer_revenue_80(invoice_request_id: int):
    """
    Allocate 80% revenue to officers based on their share percentages.
    Called when an invoice request is approved.
    """
    from datetime import date

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice request details
        cursor.execute("""
            SELECT ir.*, a.id as assignment_id
            FROM invoice_requests ir
            JOIN assignments a ON ir.assignment_id = a.id
            WHERE ir.id = ?
        """, (invoice_request_id,))
        invoice = cursor.fetchone()

        if not invoice:
            return

        invoice_amount = invoice['invoice_amount']
        fy_period = invoice['fy_period']
        assignment_id = invoice['assignment_id']
        revenue_80 = invoice_amount * 0.8

        # Update the invoice request with 80% amount
        cursor.execute("""
            UPDATE invoice_requests SET revenue_recognized_80 = ? WHERE id = ?
        """, (revenue_80, invoice_request_id))

        # Get officer shares for this assignment
        cursor.execute("""
            SELECT officer_id, share_percent FROM revenue_shares
            WHERE assignment_id = ?
        """, (assignment_id,))
        shares = cursor.fetchall()

        # Allocate to each officer
        for share in shares:
            officer_amount = revenue_80 * (share['share_percent'] / 100)
            cursor.execute("""
                INSERT INTO officer_revenue_ledger
                (officer_id, assignment_id, invoice_request_id, revenue_type,
                 share_percent, amount, fy_period, transaction_date)
                VALUES (?, ?, ?, 'INVOICE_80', ?, ?, ?, ?)
            """, (share['officer_id'], assignment_id, invoice_request_id,
                  share['share_percent'], officer_amount, fy_period, date.today().isoformat()))


def allocate_officer_revenue_20(payment_receipt_id: int):
    """
    Allocate remaining 20% revenue to officers when payment is received.
    Called when a payment receipt is recorded.
    """
    from datetime import date

    with get_db() as conn:
        cursor = conn.cursor()

        # Get payment receipt and linked invoice details
        cursor.execute("""
            SELECT pr.*, ir.invoice_amount, ir.assignment_id, ir.fy_period
            FROM payment_receipts pr
            JOIN invoice_requests ir ON pr.invoice_request_id = ir.id
            WHERE pr.id = ?
        """, (payment_receipt_id,))
        payment = cursor.fetchone()

        if not payment:
            return

        invoice_amount = payment['invoice_amount']
        assignment_id = payment['assignment_id']
        fy_period = payment['fy_period']
        revenue_20 = invoice_amount * 0.2

        # Update the payment receipt with 20% amount
        cursor.execute("""
            UPDATE payment_receipts SET revenue_recognized_20 = ? WHERE id = ?
        """, (revenue_20, payment_receipt_id))

        # Get officer shares for this assignment
        cursor.execute("""
            SELECT officer_id, share_percent FROM revenue_shares
            WHERE assignment_id = ?
        """, (assignment_id,))
        shares = cursor.fetchall()

        # Allocate to each officer
        for share in shares:
            officer_amount = revenue_20 * (share['share_percent'] / 100)
            cursor.execute("""
                INSERT INTO officer_revenue_ledger
                (officer_id, assignment_id, payment_receipt_id, revenue_type,
                 share_percent, amount, fy_period, transaction_date)
                VALUES (?, ?, ?, 'PAYMENT_20', ?, ?, ?, ?)
            """, (share['officer_id'], assignment_id, payment_receipt_id,
                  share['share_percent'], officer_amount, fy_period, date.today().isoformat()))


def get_officer_revenue_summary(officer_id: str, fy_period: str = None) -> dict:
    """
    Get officer's revenue summary with 80-20 breakdown.
    """
    if not fy_period:
        fy_period = get_current_fy()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get invoice-based revenue (80%)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM officer_revenue_ledger
            WHERE officer_id = ? AND revenue_type = 'INVOICE_80' AND fy_period = ?
        """, (officer_id, fy_period))
        invoice_revenue = cursor.fetchone()['total'] or 0

        # Get payment-based revenue (20%)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM officer_revenue_ledger
            WHERE officer_id = ? AND revenue_type = 'PAYMENT_20' AND fy_period = ?
        """, (officer_id, fy_period))
        payment_revenue = cursor.fetchone()['total'] or 0

        # Get assignment count
        cursor.execute("""
            SELECT COUNT(DISTINCT assignment_id) as count
            FROM officer_revenue_ledger
            WHERE officer_id = ? AND fy_period = ?
        """, (officer_id, fy_period))
        assignment_count = cursor.fetchone()['count'] or 0

        return {
            'officer_id': officer_id,
            'fy_period': fy_period,
            'invoice_revenue_80': round(invoice_revenue, 2),
            'payment_revenue_20': round(payment_revenue, 2),
            'total_revenue': round(invoice_revenue + payment_revenue, 2),
            'assignment_count': assignment_count
        }


# ============================================================
# PHASE-1 UPGRADE: Grievance Escalation Functions
# ============================================================

def calculate_escalation_due_date(created_at, current_level: str):
    """Calculate when a grievance should auto-escalate based on level."""
    from datetime import datetime, timedelta

    if isinstance(created_at, str):
        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    else:
        created = created_at

    # Escalation timelines per PPT:
    # TL level: 7 days
    # HEAD level: 14 days (days 8-21)
    # DDG level: 7 days (days 22+)
    escalation_days = {
        'TL': 7,
        'HEAD': 14,
        'DDG': 7,
        'DG': None  # Final level, no escalation
    }

    days = escalation_days.get(current_level)
    if days:
        return (created + timedelta(days=days)).date()
    return None


def check_and_escalate_grievances():
    """
    Check for grievances that need auto-escalation.
    Should be called by a scheduled job.
    """
    from datetime import date

    escalation_order = ['TL', 'HEAD', 'DDG', 'DG']

    with get_db() as conn:
        cursor = conn.cursor()

        # Find grievances past their escalation due date
        cursor.execute("""
            SELECT * FROM grievance_tickets
            WHERE status IN ('OPEN', 'IN_PROGRESS', 'ESCALATED')
            AND escalation_due_date <= ?
            AND current_level != 'DG'
        """, (date.today().isoformat(),))

        tickets = cursor.fetchall()

        for ticket in tickets:
            current_idx = escalation_order.index(ticket['current_level'])
            if current_idx < len(escalation_order) - 1:
                new_level = escalation_order[current_idx + 1]

                # Record escalation
                cursor.execute("""
                    INSERT INTO grievance_escalations
                    (ticket_id, from_level, to_level, from_handler, auto_escalated, escalation_reason)
                    VALUES (?, ?, ?, ?, 1, 'Auto-escalated due to timeline breach')
                """, (ticket['id'], ticket['current_level'], new_level, ticket['assigned_to']))

                # Update ticket
                new_due_date = calculate_escalation_due_date(date.today(), new_level)
                cursor.execute("""
                    UPDATE grievance_tickets
                    SET current_level = ?, status = 'ESCALATED',
                        escalation_due_date = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_level, new_due_date.isoformat() if new_due_date else None, ticket['id']))


# ============================================================
# PHASE-1 UPGRADE: Pre-Revenue Workflow Metrics
# ============================================================

def get_pre_revenue_metrics(officer_id: str = None, office_id: str = None, fy_period: str = None) -> dict:
    """
    Get pre-revenue activity metrics (Enquiry → Proposal stages).
    Per PPT requirements for tracking officer activity before work orders.
    """
    if not fy_period:
        fy_period = get_current_fy()

    # Calculate FY date range
    fy_parts = fy_period.split('-')
    fy_start = f"{fy_parts[0]}-04-01"
    fy_end = f"20{fy_parts[1]}-03-31"

    with get_db() as conn:
        cursor = conn.cursor()

        conditions = ["created_at >= ? AND created_at <= ?"]
        params = [fy_start, fy_end]

        if officer_id:
            conditions.append("officer_id = ?")
            params.append(officer_id)
        if office_id:
            conditions.append("office_id = ?")
            params.append(office_id)

        where_clause = " AND ".join(conditions)

        # Enquiries allocated
        cursor.execute(f"""
            SELECT COUNT(*) as count FROM enquiries WHERE {where_clause}
        """, params)
        enquiries_allocated = cursor.fetchone()['count']

        # Enquiries converted to PR
        cursor.execute(f"""
            SELECT COUNT(*) as count FROM enquiries
            WHERE {where_clause} AND status = 'CONVERTED_TO_PR'
        """, params)
        enquiries_converted = cursor.fetchone()['count']

        # Proposal Requests
        cursor.execute(f"""
            SELECT COUNT(*) as count FROM proposal_requests WHERE {where_clause}
        """, params)
        prs_created = cursor.fetchone()['count']

        # Proposals submitted
        cursor.execute(f"""
            SELECT COUNT(*) as count, COALESCE(SUM(proposed_value), 0) as total_value
            FROM proposals WHERE {where_clause}
        """, params)
        proposals = cursor.fetchone()
        proposals_submitted = proposals['count']
        total_proposed_value = proposals['total_value']

        # Proposals won (converted to work order)
        cursor.execute(f"""
            SELECT COUNT(*) as count, COALESCE(SUM(proposed_value), 0) as total_value
            FROM proposals WHERE {where_clause} AND status = 'WON'
        """, params)
        won = cursor.fetchone()
        proposals_won = won['count']
        total_won_value = won['total_value']

        conversion_rate = (proposals_won / proposals_submitted * 100) if proposals_submitted > 0 else 0

        return {
            'fy_period': fy_period,
            'enquiries_allocated': enquiries_allocated,
            'enquiries_converted': enquiries_converted,
            'enquiry_conversion_rate': round(enquiries_converted / enquiries_allocated * 100, 2) if enquiries_allocated > 0 else 0,
            'proposal_requests': prs_created,
            'proposals_submitted': proposals_submitted,
            'total_proposed_value': round(total_proposed_value, 2),
            'proposals_won': proposals_won,
            'total_won_value': round(total_won_value, 2),
            'proposal_conversion_rate': round(conversion_rate, 2)
        }


if __name__ == "__main__":
    init_database()
