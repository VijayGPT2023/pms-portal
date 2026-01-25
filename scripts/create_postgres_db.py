"""
Script to create PostgreSQL database for PMS Portal.
Run this once to create the database before running the application.
"""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Connection details
DB_HOST = "localhost"
DB_PORT = "5432"
DB_USER = "postgres"
DB_PASSWORD = "vjad2008"
DB_NAME = "pms_portal"

def create_database():
    """Create the pms_portal database if it doesn't exist."""
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

        # Check if database exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'")
        exists = cursor.fetchone()

        if exists:
            print(f"Database '{DB_NAME}' already exists.")
        else:
            cursor.execute(f"CREATE DATABASE {DB_NAME}")
            print(f"Database '{DB_NAME}' created successfully!")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        return False

    return True


if __name__ == "__main__":
    if create_database():
        print("\nDatabase is ready!")
        print(f"Connection URL: postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
