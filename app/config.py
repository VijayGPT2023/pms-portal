"""
Application configuration settings.
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/pms_portal.db")
DATABASE_PATH = BASE_DIR / "pms_portal.db"

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production-123!")
SESSION_COOKIE_NAME = "pms_session"
SESSION_MAX_AGE = 60 * 60 * 24  # 24 hours in seconds

# File paths
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
OFFICER_DATA_FILE = BASE_DIR / "Officer Data.xlsx"
MIS_DATA_FILE = BASE_DIR / "Revenue Sharing Detailed MIS-1.xlsx"
INITIAL_PASSWORDS_FILE = BASE_DIR / "initial_passwords.csv"

# Assignment types
ASSIGNMENT_TYPES = ["ASSIGNMENT", "TRAINING"]

# Status options
ASSIGNMENT_STATUS_OPTIONS = [
    "Not Started",
    "Ongoing",
    "Completed",
    "On Hold",
    "Cancelled"
]

# Domain options (derived from MIS data)
DOMAIN_OPTIONS = [
    "ES",  # Economic Services
    "IE",  # Industrial Engineering
    "HRM",  # Human Resource Management
    "IT",  # Information Technology
    "Agri",  # Agri-Business
    "TM",  # Training & Management
    "General"
]

# Client type options
CLIENT_TYPE_OPTIONS = [
    "Central Government",
    "State Government",
    "PSU",
    "Private",
    "International",
    "Others"
]
