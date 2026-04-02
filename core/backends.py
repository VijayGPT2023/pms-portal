"""Custom authentication backend for email-based login."""
from django.contrib.auth.backends import ModelBackend
from .models import Officer


class EmailBackend(ModelBackend):
    """Authenticate using email instead of username."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        # Also support 'username' kwarg for Django admin compat
        if email is None:
            email = kwargs.get("username")
        if email is None:
            return None
        try:
            user = Officer.objects.get(email=email.lower().strip())
        except Officer.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
