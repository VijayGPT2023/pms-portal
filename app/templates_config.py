"""
Shared Jinja2 templates configuration with custom filters.
All route modules should import templates from here.
"""
from pathlib import Path
from datetime import datetime
import json
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# Custom Jinja2 filters for PostgreSQL datetime compatibility
def format_date(value, format_str='%Y-%m-%d'):
    """Format a datetime object or string to date string."""
    if value is None:
        return '-'
    if isinstance(value, str):
        return value[:10] if len(value) >= 10 else value
    if isinstance(value, datetime):
        return value.strftime(format_str)
    return str(value)[:10] if len(str(value)) >= 10 else str(value)


def format_datetime(value, format_str='%Y-%m-%d %H:%M:%S'):
    """Format a datetime object or string to datetime string."""
    if value is None:
        return '-'
    if isinstance(value, str):
        return value[:19] if len(value) >= 19 else value
    if isinstance(value, datetime):
        return value.strftime(format_str)
    return str(value)[:19] if len(str(value)) >= 19 else str(value)


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def safe_tojson(value):
    """Safely convert value to JSON, handling datetime objects."""
    return json.dumps(value, default=json_serial)


# Register custom filters
templates.env.filters['format_date'] = format_date
templates.env.filters['format_datetime'] = format_datetime
templates.env.filters['safe_tojson'] = safe_tojson
