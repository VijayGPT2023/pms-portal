"""
Setup initial role assignments for officers.
Run this script to configure the role hierarchy.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db, init_database, USE_POSTGRES

def setup_roles():
    """Setup initial role assignments."""
    # Initialize database to ensure tables exist
    init_database()

    with get_db() as conn:
        cursor = conn.cursor()

        # Find Umashankar (name is "Uma Shankar Prasad") and Shirish Paliwal
        cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE '%Uma%Shankar%' OR name LIKE '%Umashankar%'")
        umashankar = cursor.fetchone()

        cursor.execute("SELECT officer_id, name FROM officers WHERE name LIKE '%Shirish%' OR name LIKE '%Paliwal%'")
        shirish = cursor.fetchone()

        if umashankar:
            print(f"Found Umashankar: {umashankar['name']} ({umashankar['officer_id']})")

            # Remove existing roles for this officer first
            if USE_POSTGRES:
                cursor.execute("DELETE FROM officer_roles WHERE officer_id = %s", (umashankar['officer_id'],))
            else:
                cursor.execute("DELETE FROM officer_roles WHERE officer_id = ?", (umashankar['officer_id'],))

            # Assign DDG-I role
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (%s, 'DDG-I', 'GLOBAL', NULL, 1, 'ADMIN')
                """, (umashankar['officer_id'],))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (?, 'DDG-I', 'GLOBAL', NULL, 1, 'ADMIN')
                """, (umashankar['officer_id'],))

            # Assign Group Head HRM role (scope_value is the actual office_id)
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (%s, 'GROUP_HEAD', 'GROUP', 'HRM Group', 0, 'ADMIN')
                """, (umashankar['officer_id'],))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (?, 'GROUP_HEAD', 'GROUP', 'HRM Group', 0, 'ADMIN')
                """, (umashankar['officer_id'],))

            # Assign Team Leader role
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (%s, 'TEAM_LEADER', 'ASSIGNMENT', NULL, 0, 'ADMIN')
                """, (umashankar['officer_id'],))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (?, 'TEAM_LEADER', 'ASSIGNMENT', NULL, 0, 'ADMIN')
                """, (umashankar['officer_id'],))

            # Update legacy admin_role_id
            if USE_POSTGRES:
                cursor.execute("""
                    UPDATE officers SET admin_role_id = 'DDG-I' WHERE officer_id = %s
                """, (umashankar['officer_id'],))
            else:
                cursor.execute("""
                    UPDATE officers SET admin_role_id = 'DDG-I' WHERE officer_id = ?
                """, (umashankar['officer_id'],))

            print("  - Assigned DDG-I (Primary)")
            print("  - Assigned Group Head (HRM Group)")
            print("  - Assigned Team Leader")

        else:
            print("Umashankar not found in database")

        if shirish:
            print(f"Found Shirish Paliwal: {shirish['name']} ({shirish['officer_id']})")

            # Remove existing roles for this officer first
            if USE_POSTGRES:
                cursor.execute("DELETE FROM officer_roles WHERE officer_id = %s", (shirish['officer_id'],))
            else:
                cursor.execute("DELETE FROM officer_roles WHERE officer_id = ?", (shirish['officer_id'],))

            # Assign DDG-II role
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (%s, 'DDG-II', 'GLOBAL', NULL, 1, 'ADMIN')
                """, (shirish['officer_id'],))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (?, 'DDG-II', 'GLOBAL', NULL, 1, 'ADMIN')
                """, (shirish['officer_id'],))

            # Assign Group Head Finance role (scope_value is the actual office_id)
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (%s, 'GROUP_HEAD', 'GROUP', 'Finance Group', 0, 'ADMIN')
                """, (shirish['officer_id'],))
            else:
                cursor.execute("""
                    INSERT INTO officer_roles
                    (officer_id, role_type, scope_type, scope_value, is_primary, assigned_by)
                    VALUES (?, 'GROUP_HEAD', 'GROUP', 'Finance Group', 0, 'ADMIN')
                """, (shirish['officer_id'],))

            # Update legacy admin_role_id
            if USE_POSTGRES:
                cursor.execute("""
                    UPDATE officers SET admin_role_id = 'DDG-II' WHERE officer_id = %s
                """, (shirish['officer_id'],))
            else:
                cursor.execute("""
                    UPDATE officers SET admin_role_id = 'DDG-II' WHERE officer_id = ?
                """, (shirish['officer_id'],))

            print("  - Assigned DDG-II (Primary)")
            print("  - Assigned Group Head (Finance)")

        else:
            print("Shirish Paliwal not found in database")

        # Clear and rebuild reporting hierarchy
        cursor.execute("DELETE FROM reporting_hierarchy")
        print("\nRebuilding reporting hierarchy...")

        # Groups reporting to DDG-I (use actual office_id values)
        ddg1_groups = ['IE Group', 'AB Group', 'ES Group', 'IT Group', 'Admin Group']
        ddg1_offices = ['RD Chennai', 'RD Hyderabad', 'RD Bengaluru', 'RD Gandhinagar', 'RD Mumbai', 'RD Jaipur']

        # Groups reporting to DDG-II (use actual office_id values)
        ddg2_groups = ['ECA Group', 'EM Group', 'IS Group', 'Finance Group', 'HRM Group']
        ddg2_offices = ['RD Chandigarh', 'RD Kanpur', 'RD Guwahati', 'RD Patna', 'RD Kolkata', 'RD Bhubneswar']

        for group in ddg1_groups:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('GROUP', %s, 'DDG-I')
                    ON CONFLICT DO NOTHING
                """, (group,))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('GROUP', ?, 'DDG-I')
                """, (group,))

        for office in ddg1_offices:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', %s, 'DDG-I')
                    ON CONFLICT DO NOTHING
                """, (office,))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', ?, 'DDG-I')
                """, (office,))

        for group in ddg2_groups:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('GROUP', %s, 'DDG-II')
                    ON CONFLICT DO NOTHING
                """, (group,))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('GROUP', ?, 'DDG-II')
                """, (group,))

        for office in ddg2_offices:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', %s, 'DDG-II')
                    ON CONFLICT DO NOTHING
                """, (office,))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO reporting_hierarchy (entity_type, entity_value, reports_to_role)
                    VALUES ('OFFICE', ?, 'DDG-II')
                """, (office,))

        print("Reporting hierarchy updated.")

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
