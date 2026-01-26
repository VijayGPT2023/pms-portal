"""
Script to add DG NPC user to the database.
Run this script to create the Director General user.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, USE_POSTGRES
from app.auth import hash_password
from datetime import date


def add_dg_user():
    """Add the DG NPC user to the database."""
    print("Adding DG NPC user...")

    with get_db() as conn:
        cursor = conn.cursor()

        # First check if NPC-HQ office exists, create if not
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO offices (office_id, office_name)
                VALUES ('NPC-HQ', 'NPC Headquarters')
                ON CONFLICT (office_id) DO NOTHING
            """)
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO offices (office_id, office_name)
                VALUES ('NPC-HQ', 'NPC Headquarters')
            """)

        # Create the DG NPC user
        # Default password: DGNPC@2024 (should be changed on first login)
        password_hash = hash_password('DGNPC@2024')

        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO officers (officer_id, name, email, password_hash, office_id, designation, is_active, admin_role_id)
                VALUES ('DG-NPC', 'Director General NPC', 'dg.npc@npcindia.gov.in', %s, 'NPC-HQ', 'Director General', 1, 'DG')
                ON CONFLICT (officer_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    designation = EXCLUDED.designation,
                    admin_role_id = EXCLUDED.admin_role_id
            """, (password_hash,))
        else:
            # Check if user exists
            cursor.execute("SELECT officer_id FROM officers WHERE officer_id = 'DG-NPC'")
            if cursor.fetchone():
                cursor.execute("""
                    UPDATE officers SET
                        name = 'Director General NPC',
                        email = 'dg.npc@npcindia.gov.in',
                        designation = 'Director General',
                        admin_role_id = 'DG'
                    WHERE officer_id = 'DG-NPC'
                """)
                print("DG NPC user updated.")
            else:
                cursor.execute("""
                    INSERT INTO officers (officer_id, name, email, password_hash, office_id, designation, is_active, admin_role_id)
                    VALUES ('DG-NPC', 'Director General NPC', 'dg.npc@npcindia.gov.in', ?, 'NPC-HQ', 'Director General', 1, 'DG')
                """, (password_hash,))
                print("DG NPC user created.")

        # Add DG role in officer_roles
        today = date.today().isoformat()

        # Check if role exists
        cursor.execute("""
            SELECT id FROM officer_roles
            WHERE officer_id = 'DG-NPC' AND role_type = 'DG'
        """)
        existing_role = cursor.fetchone()

        if existing_role:
            if USE_POSTGRES:
                cursor.execute("""
                    UPDATE officer_roles SET is_primary = 1, effective_from = %s
                    WHERE officer_id = 'DG-NPC' AND role_type = 'DG'
                """, (today,))
            else:
                cursor.execute("""
                    UPDATE officer_roles SET is_primary = 1, effective_from = ?
                    WHERE officer_id = 'DG-NPC' AND role_type = 'DG'
                """, (today,))
            print("DG role updated.")
        else:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, effective_from)
                    VALUES ('DG-NPC', 'DG', 'GLOBAL', 'ALL', 1, %s)
                """, (today,))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles (officer_id, role_type, scope_type, scope_value, is_primary, effective_from)
                    VALUES ('DG-NPC', 'DG', 'GLOBAL', 'ALL', 1, ?)
                """, (today,))
            print("DG role assigned.")

        conn.commit()
        print("\n" + "=" * 50)
        print("DG NPC User Created Successfully!")
        print("=" * 50)
        print("Email: dg.npc@npcindia.gov.in")
        print("Password: DGNPC@2024")
        print("Role: Director General (GLOBAL scope)")
        print("\nIMPORTANT: Please change the password after first login!")
        print("=" * 50)


if __name__ == "__main__":
    add_dg_user()
