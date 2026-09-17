# NEW FILE (Signup Forms feature)
from django.apps import AppConfig


class SignupFormsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "signup_forms"

    def ready(self):
        # Registers the CORS allowance for this app's two public endpoints
        # (public form detail + public form submission) — see cors.py's
        # module docstring for why this is done via a signal instead of a
        # global CORS_ALLOW_ALL_ORIGINS/CORS_ALLOWED_ORIGINS change.
        from . import cors  # noqa: F401
