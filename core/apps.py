from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        # Connect signal receivers for auth audit + axes lockout email.
        from . import signals  # noqa: F401
