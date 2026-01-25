"""
Script to import officers from Officer Data.xlsx and create login accounts.
Generates random passwords and saves them to initial_passwords.csv.
Sets up designation-based revenue targets:
- Assistant Director: 30L
- Dy. Director: 50L
- Director-II: 60L
- Director-I: 70L
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import csv
from app.database import init_database, get_db, get_target_for_designation, DESIGNATION_TARGETS, USE_POSTGRES
from app.auth import hash_password
from app.config import OFFICER_DATA_FILE, INITIAL_PASSWORDS_FILE


def import_officers():
    """Import officers from Excel file and create accounts."""

    # Initialize database first
    init_database()

    # Read Excel file (skip first row which is empty, use second row as header)
    print(f"Reading officers from: {OFFICER_DATA_FILE}")
    df = pd.read_excel(OFFICER_DATA_FILE, skiprows=1)

    print(f"Found {len(df)} officers in file")
    print(f"Columns: {list(df.columns)}")

    # Show designation-based targets
    print("\nDesignation-based Revenue Targets:")
    for designation, target in DESIGNATION_TARGETS.items():
        print(f"  {designation}: Rs.{target}L")

    # Prepare password file
    passwords = []

    # First, create all offices in separate transactions to avoid PostgreSQL transaction issues
    office_ids = df['OFFICE ID'].dropna().unique()
    print(f"\nCreating {len(office_ids)} offices...")

    for office_id in office_ids:
        office_id = str(office_id).strip()
        if office_id:
            try:
                with get_db() as conn:
                    cursor = conn.cursor()
                    if USE_POSTGRES:
                        cursor.execute(
                            """INSERT INTO offices (office_id, office_name)
                               VALUES (%s, %s)
                               ON CONFLICT (office_id) DO NOTHING""",
                            (office_id, f"{office_id} Office")
                        )
                    else:
                        cursor.execute(
                            """INSERT OR IGNORE INTO offices
                               (office_id, office_name)
                               VALUES (?, ?)""",
                            (office_id, f"{office_id} Office")
                        )
            except Exception as e:
                print(f"  Error creating office {office_id}: {e}")

    # Now import officers - each in its own transaction to avoid cascade failures
    print(f"\nImporting officers...")
    success_count = 0
    skip_count = 0

    for idx, row in df.iterrows():
        try:
            officer_id = str(row['EMP ID']).strip() if pd.notna(row['EMP ID']) else None
            name = str(row['Employee Name']).strip() if pd.notna(row['Employee Name']) else None
            email = str(row['EMAIL']).strip().lower() if pd.notna(row['EMAIL']) else None
            office_id = str(row['OFFICE ID']).strip() if pd.notna(row['OFFICE ID']) else None
            designation = str(row['Designation']).strip() if pd.notna(row['Designation']) else None
            discipline = str(row['Discipline']).strip() if pd.notna(row['Discipline']) else None
            admin_role = str(row['Admin_Role ID']).strip() if pd.notna(row.get('Admin_Role ID')) else None

            # Skip if missing required fields
            if not officer_id or not name or not email or not office_id:
                print(f"  Skipping row {idx}: Missing required fields")
                skip_count += 1
                continue

            # Use fixed password for all users
            password = "npc123@#"
            password_hash = hash_password(password)

            # Get target based on designation
            annual_target = get_target_for_designation(designation)

            # Insert officer in its own transaction
            with get_db() as conn:
                cursor = conn.cursor()
                if USE_POSTGRES:
                    cursor.execute("""
                        INSERT INTO officers
                        (officer_id, name, email, designation, discipline, office_id, admin_role_id,
                         password_hash, is_active, annual_target)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
                        ON CONFLICT (officer_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            email = EXCLUDED.email,
                            designation = EXCLUDED.designation,
                            discipline = EXCLUDED.discipline,
                            office_id = EXCLUDED.office_id,
                            admin_role_id = EXCLUDED.admin_role_id,
                            password_hash = EXCLUDED.password_hash,
                            is_active = 1,
                            annual_target = EXCLUDED.annual_target
                    """, (officer_id, name, email, designation, discipline, office_id, admin_role,
                          password_hash, annual_target))
                else:
                    cursor.execute("""
                        INSERT OR REPLACE INTO officers
                        (officer_id, name, email, designation, discipline, office_id, admin_role_id,
                         password_hash, is_active, annual_target)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """, (officer_id, name, email, designation, discipline, office_id, admin_role,
                          password_hash, annual_target))

            # Store password for CSV output
            passwords.append({
                'officer_id': officer_id,
                'name': name,
                'email': email,
                'office_id': office_id,
                'designation': designation,
                'annual_target': annual_target,
                'password': password
            })

            success_count += 1

        except Exception as e:
            print(f"  Error importing row {idx}: {e}")
            skip_count += 1

    # Update office officer counts and calculate annual targets based on officers
    print(f"\nUpdating office targets...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE offices SET
                officer_count = (
                    SELECT COUNT(*) FROM officers
                    WHERE officers.office_id = offices.office_id AND officers.is_active = 1
                ),
                annual_revenue_target = (
                    SELECT COALESCE(SUM(annual_target), 0) FROM officers
                    WHERE officers.office_id = offices.office_id AND officers.is_active = 1
                )
        """)

        # Show office-wise summary
        cursor.execute("""
            SELECT office_id, officer_count, annual_revenue_target
            FROM offices
            ORDER BY annual_revenue_target DESC
        """)
        print("\nOffice-wise Targets (sum of officer targets):")
        print(f"{'Office':<20} {'Officers':>10} {'Target (L)':>15}")
        print("-" * 47)
        for row in cursor.fetchall():
            print(f"{row['office_id']:<20} {row['officer_count']:>10} {row['annual_revenue_target']:>15.2f}")

        # Show designation-wise summary
        cursor.execute("""
            SELECT designation, COUNT(*) as count, SUM(annual_target) as total_target
            FROM officers
            WHERE is_active = 1
            GROUP BY designation
            ORDER BY total_target DESC
        """)
        print("\nDesignation-wise Summary:")
        print(f"{'Designation':<30} {'Count':>8} {'Total Target (L)':>18}")
        print("-" * 58)
        for row in cursor.fetchall():
            desg = row['designation'] or 'Unspecified'
            print(f"{desg[:30]:<30} {row['count']:>8} {row['total_target']:>18.2f}")

    # Add admin user to passwords list
    admin_password = {
        'officer_id': 'ADMIN',
        'name': 'System Administrator',
        'email': 'admin@npcindia.gov.in',
        'office_id': 'HQ',
        'designation': 'System Admin',
        'annual_target': 0,
        'password': 'Admin@NPC2024'
    }

    # Write passwords to CSV (admin first)
    print(f"\nWriting passwords to: {INITIAL_PASSWORDS_FILE}")
    with open(INITIAL_PASSWORDS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['officer_id', 'name', 'email', 'office_id',
                                               'designation', 'annual_target', 'password'])
        writer.writeheader()
        writer.writerow(admin_password)  # Admin first
        writer.writerows(passwords)

    print(f"\n{'='*50}")
    print(f"Import complete!")
    print(f"  Officers imported: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Passwords saved to: {INITIAL_PASSWORDS_FILE}")
    print(f"{'='*50}")

    return success_count


if __name__ == "__main__":
    import_officers()
