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

    print("\n" + "=" * 60)
    print("DATABASE INITIALIZATION COMPLETE!")
    print("=" * 60)


def create_default_admin():
    """Create a default admin user if officer import fails."""
    from app.auth import hash_password

    with get_db() as conn:
        cursor = conn.cursor()

        # Create default office if not exists
        cursor.execute("""
            INSERT INTO offices (office_id, office_name, office_type, region)
            VALUES ('HQ', 'Headquarters', 'HQ', 'National')
            ON CONFLICT (office_id) DO NOTHING
        """ if USE_POSTGRES else """
            INSERT OR IGNORE INTO offices (office_id, office_name, office_type, region)
            VALUES ('HQ', 'Headquarters', 'HQ', 'National')
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
