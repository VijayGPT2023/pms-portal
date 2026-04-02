"""
Django settings for PMS Portal.
Supports SQLite (dev) and PostgreSQL (production).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file if it exists
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-change-me-in-production-123!")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:8000").split(",")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_htmx",
    "django_fsm",
    "auditlog",
    "widget_tweaks",
    # Project
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

ROOT_URLCONF = "pms_portal.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.global_context",
            ],
        },
    },
]

WSGI_APPLICATION = "pms_portal.wsgi.application"

# Database — SQLite for dev, PostgreSQL for production
DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres"):
    # Render.com uses postgres:// but Django needs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DATABASE_URL,
            "CONN_MAX_AGE": 600,
            "OPTIONS": {},
        }
    }
    # Use dj-database-url style parsing
    import re
    match = re.match(
        r"postgresql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:/]+):?(?P<port>\d+)?/(?P<name>.+)",
        DATABASE_URL,
    )
    if match:
        DATABASES["default"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": match.group("name"),
            "USER": match.group("user"),
            "PASSWORD": match.group("password"),
            "HOST": match.group("host"),
            "PORT": match.group("port") or "5432",
            "CONN_MAX_AGE": 600,
        }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Custom User Model
AUTH_USER_MODEL = "core.Officer"

# Password validation
# Authentication backends
AUTHENTICATION_BACKENDS = [
    "core.backends.EmailBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Session settings
SESSION_COOKIE_NAME = "pms_session"
SESSION_COOKIE_AGE = 60 * 60 * 24  # 24 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# Login/Logout URLs
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# Static files — self-hosted for GIGW 3.0 compliance
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Media files (uploads)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "uploads"

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# django-auditlog
AUDITLOG_INCLUDE_ALL_MODELS = True

# =============================================================================
# Production Security (applied when DEBUG=False)
# =============================================================================
if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() == "true"
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# =============================================================================
# PMS Portal Business Configuration
# =============================================================================

# Assignment types
ASSIGNMENT_TYPES = ["ASSIGNMENT", "TRAINING", "DEVELOPMENT"]

# Development Work — notional value calculation
DAILY_RATE_LAKHS = 0.20  # 20k per day = 0.20 Lakhs

ASSIGNMENT_STATUS_OPTIONS = [
    "Not Started", "Ongoing", "Completed", "On Hold", "Cancelled"
]

DOMAIN_OPTIONS = [
    ("ES", "Economic Services"),
    ("IE", "Industrial Engineering"),
    ("HRM", "Human Resource Management"),
    ("IT", "Information Technology"),
    ("Agri", "Agri-Business"),
    ("TM", "Training & Management"),
    ("General", "General"),
]

CLIENT_TYPE_OPTIONS = [
    ("CG", "Central Government"),
    ("SG", "State Government"),
    ("PSU", "PSU"),
    ("PVT", "Private"),
    ("INT", "International"),
    ("OTH", "Others"),
]

# Feature flags
SHOW_RANKINGS = False
TRAINING_MODE = True

# Revenue weightage
REVENUE_WEIGHTAGE_REAL = 1.0
REVENUE_WEIGHTAGE_NOTIONAL = 0.5

# Development Work Quantification Rules (man-days)
DEV_WORK_QUANTIFICATION = {
    "PROPOSAL_PREP": {
        "slabs": [
            (20, 1), (50, 2), (100, 3), (200, 4), (float("inf"), 5),
        ]
    },
    "EVENT_MGMT": {"max_days": 5},
    "COMMITTEE": {"per_member_days": 0.25},
    "MEETING": {"min_days": 0.5},
}

# File upload
ALLOWED_UPLOAD_EXTENSIONS = [
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".png"
]

# Activity number format
ACTIVITY_NUMBER_FORMAT = "NPC/{office_id}/{type_code}/{client_code}/{seq:04d}/{fy}"
ACTIVITY_TYPE_CODES = {
    "ASSIGNMENT": "ASG",
    "TRAINING": "TRG",
    "DEVELOPMENT": "DEV",
}

# Utilization claim types
UTILIZATION_CLAIM_TYPES = [
    ("ASSIGNMENT_WORK", "Assignment Work"),
    ("PROPOSAL_PREP", "Proposal Preparation"),
    ("EVENT_MGMT", "Event Management"),
    ("COMMITTEE", "Committee Work"),
    ("MEETING", "Meetings/Events"),
    ("TRAVEL", "Official Travel"),
    ("LEAVE", "Leave"),
    ("OTHER", "Other"),
]

# Designation-based revenue targets (in Lakhs)
DESIGNATION_TARGETS = {
    "Assistant Director": 30.0,
    "Dy. Director": 50.0,
    "Deputy Director": 50.0,
    "Director-II": 60.0,
    "Director-I": 70.0,
    "Director": 60.0,
}
DEFAULT_TARGET = 60.0
