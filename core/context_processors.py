"""
Global template context processor.
Injects common data into all templates.
"""
from django.conf import settings


def global_context(request):
    """Add global context variables available to all templates."""
    return {
        "DOMAIN_OPTIONS": settings.DOMAIN_OPTIONS,
        "CLIENT_TYPE_OPTIONS": settings.CLIENT_TYPE_OPTIONS,
        "ASSIGNMENT_STATUS_OPTIONS": settings.ASSIGNMENT_STATUS_OPTIONS,
        "SHOW_RANKINGS": settings.SHOW_RANKINGS,
        "TRAINING_MODE": settings.TRAINING_MODE,
        "DEBUG": settings.DEBUG,
    }
