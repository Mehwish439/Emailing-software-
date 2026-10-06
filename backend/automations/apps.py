from django.apps import AppConfig


class AutomationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automations"

    def ready(self):
        # Registers the m2m_changed receiver that fires the CONTACT_ADDED
        # trigger whenever a contact joins a list (see signals.py).
        from . import signals  # noqa: F401
