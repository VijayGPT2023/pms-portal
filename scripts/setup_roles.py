"""
Setup initial role assignments for officers.
Run this script to configure the role hierarchy.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db, init_database

def setup_roles():
    """Setup initial role assignments."""
    # Initialize database to ensure tables exist
    init_database()

    with get_db() as conn:
        cursor = conn.cursor()

        # Find Umashankar and Shirish Paliwal
        cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE '%Umashankar%'")
        umashankar = cursor.fetchone()

        cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE '%Shirish%' OR name LIKE '%Paliwal%'")
        shirish = cursor.fetchone()

        if umashankar:
            print(f"Found Umashankar: {umashankar['name']} ({umashankar['officer_id']})")

            # Assign DDG-I role
            cursor.execute("""
                INSERT OR REPLACE INTO officer_roles
                (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES (?, 'DDG-I', 'GLOBAL', NULL, 1, 'ADMIN')
            """, (umashankar['officer_id'],))

            # Assign Group Head HRM role
            cursor.execute("""
                INSERT OR REPLACE INTO officer_roles
                (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES (?, 'GROUP_HEAD', 'GROUP', 'HRM', 0, 'ADMIN')
            """, (umashankar['officer_id'],))

            # Update legacy admin_role_id
            cursor.execute("""
                UPDATE officers SET admin_role_id = 'DDG-I' WHERE officer_id = ?
            """, (umashankar['officer_id'],))

            print("  - Assigned DDG-I (Primary)")
            print("  - Assigned Group Head (HRM)")

        else:
            print("Umashankar not found in database")

        if shirish:
            print(f"Found Shirish Paliwal: {shirish['name']} ({shirish['officer_id']})")

            # Assign DDG-II role
            cursor.execute("""
                INSERT OR REPLACE INTO officer_roles
                (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES (?, 'DDG-II', 'GLOBAL', NULL, 1, 'ADMIN')
            """, (shirish['officer_id'],))

            # Assign Group Head Finance role
            cursor.execute("""
                INSERT OR REPLACE INTO officer_roles
                (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                VALUES (?, 'GROUP_HEAD', 'GROUP', 'Finance', 0, 'ADMIN')
            """, (shirish['officer_id'],))

            # Update legacy admin_role_id
            cursor.execute("""
                UPDATE officers SET admin_role_id = 'DDG-II' WHERE officer_id = ?
            """, (shirish['officer_id'],))

            print("  - Assigned DDG-II (Primary)")
            print("  - Assigned Group Head (Finance)")

        else:
            print("Shirish Paliwal not found in database")

        # Verify reporting hierarchy exists
        cursor.execute("SELECT COUNT(*) FROM reporting_hierarchy")
        count = cursor.fetchone()[0]
        print(f"\nReporting hierarchy entries: {count}")

        if count == 0:
            print("Inserting default reporting hierarchy...")
            # Groups reporting to DDG-I
            ddg1_groups = ['IE', 'AB', 'ES', 'IT', 'Admin']
            ddg1_offices = ['CHN', 'HYD', 'BLR', 'GNR', 'MUM', 'JAI']

            # Groups reporting to DDG-II
            ddg2_groups = ['ECA', 'EM', 'IS', 'Finance', 'HRM']
            ddg2_offices = ['CHD', 'KNP', 'GUW', 'PAT', 'KOL', 'BBS']

            for group in ddg1_groups:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('GROUP', ?, 'DDG-I')
                """, (group,))

            for office in ddg1_offices:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', ?, 'DDG-I')
                """, (office,))

            for group in ddg2_groups:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('GROUP', ?, 'DDG-II')
                """, (group,))

            for office in ddg2_offices:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', ?, 'DDG-II')
                """, (office,))

            print("Default hierarchy inserted.")

        # Show current role assignments
        print("\n--- Current Role Assignments ---")
        cursor.execute("""
            SELECT r.*, o.name as officer_name
            FROM officer_roles r
            JOIN officers o ON r.officer_id = o.officer_id
            ORDER BY o.name
        """)
        for row in cursor.fetchall():
            scope = f"({row['scope_value']})" if row['scope_value'] else ""
            primary = "[PRIMARY]" if row['is_primary'] else ""
            print(f"  {row['officer_name']}: {row['role_type']} {scope} {primary}")

        print("\nRole setup complete!")


if __name__ == "__main__":
    setup_roles()
