"""
Master setup script that runs all initialization steps in order.
Run this after installing dependencies to set up the complete system.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import reset_database
from scripts.import_officers import import_officers
from scripts.generate_dummy_data import generate_dummy_data


def setup_all():
    """Run complete system setup."""
    print("="*60)
    print("PMS Portal - Complete Setup")
    print("="*60)

    print("\nStep 1: Initializing database...")
    print("-"*40)
    reset_database()

    print("\nStep 2: Importing officers from Excel...")
    print("-"*40)
    import_officers()

    print("\nStep 3: Generating dummy assignment data...")
    print("-"*40)
    generate_dummy_data()

    print("\n" + "="*60)
    print("SETUP COMPLETE!")
    print("="*60)
    print("\nYou can now start the server with:")
    print("  python -m uvicorn app.main:app --reload")
    print("\nOr simply run:")
    print("  python run.py")
    print("\nAccess the portal at: http://127.0.0.1:8000")
    print("\nLogin credentials are in: initial_passwords.csv")
    print("="*60)


if __name__ == "__main__":
    setup_all()
