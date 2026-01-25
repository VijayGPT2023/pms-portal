"""
Create an admin user for the PMS Portal.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from app.database import get_db, init_database


def create_admin_user():
    """Create an admin user with full access."""
    init_database()

    admin_email = "admin@npc.gov.in"
    admin_password = "Admin@123"  # Change this in production
    admin_name = "System Administrator"
    admin_officer_id = "ADMIN001"

    with get_db() as conn:
        cursor = conn.cursor()

        # Check if admin already exists
        cursor.execute("SELECT officer_id FROM officers WHERE officer_id = ?", (admin_officer_id,))
        if cursor.fetchone():
            print(f"Admin user already exists: {admin_email}")
            # Update to ensure admin role
            cursor.execute("""
                UPDATE officers SET admin_role_id = 'ADMIN' WHERE officer_id = ?
            """, (admin_officer_id,))
            print("Admin role confirmed.")
            return

        # Hash password
        password_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Ensure HQ office exists
        cursor.execute("""
            INSERT OR IGNORE INTO offices (office_id, office_name, officer_count, annual_revenue_target)
            VALUES ('HQ', 'Head Quarters', 1, 100)
        """)

        # Create admin user
        cursor.execute("""
            INSERT INTO officers
            (officer_id, name, email, designation, office_id, admin_role_id, password_hash, is_active, annual_target)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
        """, (
            admin_officer_id,
            admin_name,
            admin_email,
            'System Admin',
            'HQ',
            'ADMIN',
            password_hash
        ))

        print("="*50)
        print("Admin user created successfully!")
        print("="*50)
        print(f"  Email: {admin_email}")
        print(f"  Password: {admin_password}")
        print(f"  Officer ID: {admin_officer_id}")
        print("="*50)
        print("IMPORTANT: Change the password after first login!")
        print("="*50)


if __name__ == "__main__":
    create_admin_user()
