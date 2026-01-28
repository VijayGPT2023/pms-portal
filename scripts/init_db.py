"""
Database initialization script for Railway deployment.
Creates tables, imports officers, and generates initial data.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, USE_POSTGRES


def check_if_initialized():
    """Check if database is already initialized with full data."""
    # Force re-initialization to apply new fixed passwords
    print("Forcing fresh initialization with fixed passwords...")
    return False


def init_database():
    """Initialize the database with tables, officers, and sample data."""
    print("=" * 60, flush=True)
    print("PMS Portal - Database Initialization", flush=True)
    print(f"Database: {'PostgreSQL' if USE_POSTGRES else 'SQLite'}", flush=True)
    print("=" * 60, flush=True)

    # Check if already initialized
    if check_if_initialized():
        print("\nDatabase already initialized. Skipping.")
        print("=" * 60)
        return

    print("\nStep 1: Creating database tables...")
    print("-" * 40)
    from app.database import reset_database
    reset_database()

    print("\nStep 2: Importing officers from Excel...")
    print("-" * 40)
    try:
        from scripts.import_officers import import_officers
        import_officers()
    except Exception as e:
        print(f"Warning: Could not import officers: {e}")
        print("Creating default admin user...")
        create_default_admin()

    print("\nStep 3: Generating sample data...")
    print("-" * 40)
    try:
        from scripts.generate_dummy_data import generate_dummy_data
        generate_dummy_data()
    except Exception as e:
        print(f"Warning: Could not generate dummy data: {e}")

    print("\nStep 4: Setting up officer roles and reporting hierarchy...")
    print("-" * 40)
    try:
        setup_officer_roles()
    except Exception as e:
        print(f"Warning: Could not setup roles: {e}")

    print("\n" + "=" * 60)
    print("DATABASE INITIALIZATION COMPLETE!")
    print("=" * 60)


def setup_officer_roles():
    """Setup officer roles and reporting hierarchy (extracted from setup_roles.py)."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Find Umashankar and Shirish Paliwal
        if USE_POSTGRES:
            cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE %s OR name LIKE %s", ('%Uma%Shankar%', '%Umashankar%'))
        else:
            cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE '%Uma%Shankar%' OR name LIKE '%Umashankar%'")
        umashankar = cursor.fetchone()

        if USE_POSTGRES:
            cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE %s OR name LIKE %s", ('%Shirish%', '%Paliwal%'))
        else:
            cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE '%Shirish%' OR name LIKE '%Paliwal%'")
        shirish = cursor.fetchone()

        ph = '%s' if USE_POSTGRES else '?'

        if umashankar:
            oid = umashankar['officer_id']
            print(f"  Setting up roles for {umashankar['name']} ({oid})")
            cursor.execute(f"DELETE FROM officer_roles WHERE officer_id = {ph}", (oid,))
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'DDG-I', 'GLOBAL', NULL, 1, 'ADMIN')
            """, (oid,))
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'GROUP_HEAD', 'GROUP', 'HRM Group', 0, 'ADMIN')
            """, (oid,))
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'TEAM_LEADER', 'ASSIGNMENT', NULL, 0, 'ADMIN')
            """, (oid,))
            cursor.execute(f"UPDATE officers SET admin_role_id = 'DDG-I' WHERE officer_id = {ph}", (oid,))
            print("    DDG-I (Primary), GROUP_HEAD (HRM Group), TEAM_LEADER")
        else:
            print("  Umashankar not found")

        if shirish:
            oid = shirish['officer_id']
            print(f"  Setting up roles for {shirish['name']} ({oid})")
            cursor.execute(f"DELETE FROM officer_roles WHERE officer_id = {ph}", (oid,))
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'DDG-II', 'GLOBAL', NULL, 1, 'ADMIN')
            """, (oid,))
            cursor.execute(f"""
                INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES ({ph}, 'GROUP_HEAD', 'GROUP', 'Finance Group', 0, 'ADMIN')
            """, (oid,))
            cursor.execute(f"UPDATE officers SET admin_role_id = 'DDG-II' WHERE officer_id = {ph}", (oid,))
            print("    DDG-II (Primary), GROUP_HEAD (Finance Group)")
        else:
            print("  Shirish Paliwal not found")

        # Rebuild reporting hierarchy
        cursor.execute("DELETE FROM reporting_hierarchy")

        ddg1_groups = ['IE Group', 'AB Group', 'ES Group', 'IT Group', 'Admin Group']
        ddg1_offices = ['RD Chennai', 'RD Hyderabad', 'RD Bengaluru', 'RD Gandhinagar', 'RD Mumbai', 'RD Jaipur']
        ddg2_groups = ['ECA Group', 'EM Group', 'IS Group', 'Finance Group', 'HRM Group']
        ddg2_offices = ['RD Chandigarh', 'RD Kanpur', 'RD Guwahati', 'RD Patna', 'RD Kolkata', 'RD Bhubneswar']

        conflict = "ON CONFLICT DO NOTHING" if USE_POSTGRES else ""
        insert_prefix = "INSERT INTO" if USE_POSTGRES else "INSERT OR IGNORE INTO"

        for group in ddg1_groups:
            cursor.execute(f"{insert_prefix} reporting_hierarchy (entity_type, entity_value, reports_to_role) VALUES ('GROUP', {ph}, 'DDG-I') {conflict}", (group,))
        for office in ddg1_offices:
            cursor.execute(f"{insert_prefix} reporting_hierarchy (entity_type, entity_value, reports_to_role) VALUES ('OFFICE', {ph}, 'DDG-I') {conflict}", (office,))
        for group in ddg2_groups:
            cursor.execute(f"{insert_prefix} reporting_hierarchy (entity_type, entity_value, reports_to_role) VALUES ('GROUP', {ph}, 'DDG-II') {conflict}", (group,))
        for office in ddg2_offices:
            cursor.execute(f"{insert_prefix} reporting_hierarchy (entity_type, entity_value, reports_to_role) VALUES ('OFFICE', {ph}, 'DDG-II') {conflict}", (office,))

        print("  Reporting hierarchy configured.")


def create_default_admin():
    """Create a default admin user if officer import fails."""
    from app.auth import hash_password

    with get_db() as conn:
        cursor = conn.cursor()

        # Create default office if not exists
        cursor.execute("""
            INSERT INTO offices (office_id, office_name)
            VALUES ('HQ', 'Headquarters')
            ON CONFLICT (office_id) DO NOTHING
        """ if USE_POSTGRES else """
            INSERT OR IGNORE INTO offices (office_id, office_name)
            VALUES ('HQ', 'Headquarters')
        """)

        # Create admin user
        admin_password = hash_password('Admin@NPC2024')
        cursor.execute("""
            INSERT INTO officers (officer_id, name, email, password_hash, office_id, designation, is_active, admin_role_id)
            VALUES ('ADMIN', 'System Administrator', 'admin@npcindia.gov.in', %s, 'HQ', 'System Admin', 1, 'ADMIN')
            ON CONFLICT (officer_id) DO NOTHING
        """ if USE_POSTGRES else """
            INSERT OR IGNORE INTO officers (officer_id, name, email, password_hash, office_id, designation, is_active, admin_role_id)
            VALUES ('ADMIN', 'System Administrator', 'admin@npcindia.gov.in', ?, 'HQ', 'System Admin', 1, 'ADMIN')
        """, (admin_password,))

        print("Default admin created: admin@npcindia.gov.in / Admin@NPC2024")


if __name__ == "__main__":
    init_database()
