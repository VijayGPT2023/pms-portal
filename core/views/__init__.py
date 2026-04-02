"""
Core views package.
Re-exports all views so existing imports like `from . import views` keep working.
"""
# Auth, health — original views.py (now lives at core/views/main.py)
from core.views.main import (
    root_redirect,
    login_view,
    logout_view,
    health_check,
)

# Dashboard views
from core.views.dashboard import (
    dashboard_view as dashboard,
    dashboard_summary_view,
    monthly_breakdown_api,
    business_mis_api,
)

# Assignment views
from core.views.assignments import *  # noqa: F401,F403

# Approval views
from core.views.approvals import *  # noqa: F401,F403

# Finance views  (may not exist yet — guard import)
try:
    from core.views.finance import *  # noqa: F401,F403
except ImportError:
    pass

# Revenue views
try:
    from core.views.revenue import *  # noqa: F401,F403
except ImportError:
    pass

# Profile views
try:
    from core.views.profile import *  # noqa: F401,F403
except ImportError:
    pass

# Non-revenue views
try:
    from core.views.non_revenue import *  # noqa: F401,F403
except ImportError:
    pass
