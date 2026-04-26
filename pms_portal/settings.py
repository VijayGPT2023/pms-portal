"""
Django settings for PMS Portal.
Supports SQLite (dev) and MariaDB 10.6+ (production on DirectAdmin shared hosting).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file if it exists (dev convenience)
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# DirectAdmin-style config: user edits local_settings.py after upload.
# Safe on dev (file absent) — falls back to env vars and dev defaults.
try:
    from local_settings import *  # noqa: F401, F403
    _HAS_LOCAL = True
except ImportError:
    _HAS_LOCAL = False


def _setting(name, default=None):
    """Prefer local_settings value (already imported), then env var, then default."""
    if name in globals():
        return globals()[name]
    return os.environ.get(name, default)


# Security
SECRET_KEY = _setting("SECRET_KEY", "django-insecure-change-me-in-production-123!")
DEBUG = str(_setting("DEBUG", "True")).lower() in ("true", "1", "yes")
ALLOWED_HOSTS = [h.strip() for h in str(_setting("ALLOWED_HOSTS", "localhost,127.0.0.1")).split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in str(_setting("CSRF_TRUSTED_ORIGINS", "http://localhost:8000")).split(",") if o.strip()]

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
    "axes",
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
    # MaintenanceModeMiddleware AFTER authentication (so it can bypass for staff)
    # but BEFORE AxesMiddleware (which short-circuits requests for locked-out IPs).
    "core.middleware.MaintenanceModeMiddleware",
    # SecurityHeadersMiddleware: adds CSP, Permissions-Policy, Referrer-Policy.
    # Position late so it operates on the final response.
    "core.middleware.SecurityHeadersMiddleware",
    # AxesMiddleware MUST be last so it sees the resolved authentication outcome.
    "axes.middleware.AxesMiddleware",
]

# SecurityMiddleware (already installed at the top of MIDDLEWARE) also reads:
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# CSP enforcement toggle (default: Report-Only). Flip to True in local_settings.py
# after auditing violation reports per SCOPE_V2 §3.2 phased rollout.
CSP_ENFORCE = bool(_setting("CSP_ENFORCE", ""))

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

# Database resolution order:
#   1. MYSQL_DB set (via local_settings.py or env var) → MariaDB on DirectAdmin
#   2. else → SQLite (dev)
_MYSQL_DB = _setting("MYSQL_DB")

if _MYSQL_DB:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": _MYSQL_DB,
            "USER": _setting("MYSQL_USER", ""),
            "PASSWORD": _setting("MYSQL_PASSWORD", ""),
            "HOST": _setting("MYSQL_HOST", "localhost"),
            "PORT": str(_setting("MYSQL_PORT", "3306")),
            "CONN_MAX_AGE": 280,  # under MariaDB wait_timeout + shared-host idle cutoffs
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
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

# Authentication backends.
# AxesStandaloneBackend MUST be FIRST — it short-circuits authentication when
# an account/IP is locked out, before any password check runs. EmailBackend
# follows for the actual credential check.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "core.backends.EmailBackend",
]

# django-axes — login lockout (M0-IAM-04, IAM-05, SEC-10, SEC-19)
# Tuned for an internal officer portal: tolerant of typos, hard against bots.
AXES_FAILURE_LIMIT = 5                  # 5 failed attempts → lockout
AXES_COOLOFF_TIME = 1                   # 1 hour lockout (in hours)
AXES_RESET_ON_SUCCESS = True            # Successful login clears the counter
AXES_LOCKOUT_PARAMETERS = ["ip_address", ["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "email"      # We log in with email, not username
AXES_LOCKOUT_CALLABLE = None            # Use default lockout response
AXES_VERBOSE = True                     # Detailed logging for security review
# Optional: a friendlier locked-out template — falls back to default if absent
AXES_LOCKOUT_TEMPLATE = "axes/lockout.html"

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

# Internationalization (M0-L10N-04)
# en-in gives Django the Indian English locale: DD/MM/YYYY date format,
# Indian week start, etc. Bilingual (Hindi) UI scaffolding comes in Phase 2.5.
LANGUAGE_CODE = "en-in"
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
# On DirectAdmin, set PERSIST_DIR = /home/npcindia/pms_data so uploads survive
# re-deploys (the app folder gets overwritten every time you extract the zip).
PERSIST_DIR = _setting("PERSIST_DIR", str(BASE_DIR))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(PERSIST_DIR) / "uploads"

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Backup retention (M0-REL-03). Cron deletes backups older than this.
# Override in local_settings.py if statutory retention differs.
BACKUP_RETENTION_DAYS = int(_setting("BACKUP_RETENTION_DAYS", "30"))

# Audit log retention (M0-AUD-08, M0-COMP-02). CERT-In requires 180 days.
# `purge_audit_logs` cron uses this. Don't reduce below 180 without compliance review.
AUDIT_LOG_RETENTION_DAYS = int(_setting("AUDIT_LOG_RETENTION_DAYS", "180"))

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# django-auditlog
AUDITLOG_INCLUDE_ALL_MODELS = True

# =============================================================================
# Logging — critical on shared hosting where we have no SSH/console.
# Passenger swallows tracebacks unless we write them to a file we can tail
# via the DirectAdmin File Manager.
# =============================================================================
_LOG_FILE = _setting("LOG_FILE", "")
if _LOG_FILE:
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "[{asctime}] {levelname} {name} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": _LOG_FILE,
                "formatter": "verbose",
            },
        },
        "loggers": {
            "django": {"handlers": ["file"], "level": "INFO"},
            "django.request": {"handlers": ["file"], "level": "WARNING", "propagate": False},
            "core": {"handlers": ["file"], "level": "INFO"},
        },
    }

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
