"""
Script to drop and recreate PostgreSQL database for PMS Portal.
"""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Connection details
DB_HOST = "localhost"
DB_PORT = "5432"
DB_USER = "postgres"
DB_PASSWORD = "vjad2008"
DB_NAME = "pms_portal"

def recreate_database():
    """Drop and recreate the pms_portal database."""
    try:
        # Connect to default postgres database
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Terminate existing connections
        cursor.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{DB_NAME}'
            AND pid <> pg_backend_pid()
        """)

        # Drop database if exists
        cursor.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        print(f"Database '{DB_NAME}' dropped (if existed).")

        # Create database
        cursor.execute(f"CREATE DATABASE {DB_NAME}")
        print(f"Database '{DB_NAME}' created successfully!")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        return False

    return True


if __name__ == "__main__":
    if recreate_database():
        print("\nDatabase is ready for initialization!")
        print(f"Connection URL: postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
