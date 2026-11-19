"""
Django settings for the Email Campaign Management Platform.
All sensitive/configurable values are pulled from environment variables (.env).
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Refuse to boot in production with the well-known development key (sessions/tokens would be forgeable).
if not DEBUG and SECRET_KEY == "insecure-dev-key-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("SECRET_KEY must be set to a long random value when DEBUG is False.")

# Self-service sign-up creates a standalone account (no company, NO quota = unlimited). Set to False on a
# multi-tenant deployment where accounts must come from invitations only.
ALLOW_PUBLIC_REGISTRATION = env_bool("ALLOW_PUBLIC_REGISTRATION", True)

# Render sets RENDER_EXTERNAL_HOSTNAME automatically on every web service
# (e.g. "your-app.onrender.com") — trust it without needing to hardcode it
# into ALLOWED_HOSTS/CORS_ALLOWED_ORIGINS by hand.
_render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if _render_hostname:
    ALLOWED_HOSTS.append(_render_hostname)

# Render (and most PaaS hosts) terminate TLS at their edge proxy and forward
# requests to this app as plain HTTP, adding an X-Forwarded-Proto header
# saying what the original request actually was. Without this,
# request.is_secure() -- and anything built from request.build_absolute_uri(),
# e.g. the uploaded-image URL in email_templates/views.py -- would report
# "http" even for a real HTTPS request, producing a link the browser then
# blocks as mixed content on an HTTPS page.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",

    # local apps
    "common",
    "accounts",
    "contacts",
    "email_templates",
    "campaigns",
    "scheduling",
    "brevo",
    "analytics",
    "ab_testing",
    "signup_forms",  # NEW (Signup Forms feature)
    "automations",  # NEW (Marketing Automation feature)
    "tenancy",      # NEW (companies, plans, quota ledger, audit log)
    "providers",    # NEW (pluggable email providers: Brevo + self-hosted SMTP)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.ExceptionLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# DATABASE_URL points at Supabase's PostgreSQL connection string (found in
# your Supabase project's Settings -> Database -> Connection string). Django
# connects to it exactly like any other PostgreSQL database via the
# standard ORM — Supabase's REST/client APIs are not used anywhere here.
#
# conn_max_age=60 (persistent connections) rather than 0: gunicorn here runs
# as a genuinely long-lived process (see render.yaml's startCommand), so
# each worker can safely reuse one connection across requests instead of
# opening a brand-new one (full TCP+TLS handshake) every single request.
# This matters a lot in practice when the database is geographically far
# from where the backend is deployed (e.g. Render US/EU regions talking to
# a Supabase project in a different region) — that round trip was
# previously being paid on every request, not just once per worker.
# conn_health_checks=True guards against reusing a connection that Supabase's
# pooler (pgbouncer) may have silently closed while idle.
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv(
            "DATABASE_URL",
            "postgres://campaign_user:campaign_pass@localhost:5432/email_campaign_db",
        ),
        conn_max_age=60,
        conn_health_checks=True,
    )
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"
    },
]


# ---------------------------------------------------------------------------
# I18N / TZ
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Karachi")
USE_I18N = True
USE_TZ = True  # Always store timestamps in UTC internally


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise serves collected static files (Django admin's CSS/JS) directly
# from the Django app itself — no separate static file host/CDN needed,
# which keeps a Render deployment to a single web service. Compressed +
# hashed filenames enable long-lived caching safely.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage"
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# CORS / CSRF
# ---------------------------------------------------------------------------
def _origins(name):
    """Return normalised browser origins (scheme://host[:port], no trailing slash)."""
    return [item.rstrip("/") for item in env_list(name, "")]


def _unique_origins(*groups):
    """Merge origin lists while preserving order and removing duplicates."""
    result = []
    for group in groups:
        for origin in group:
            origin = origin.strip().rstrip("/")
            if origin and origin not in result:
                result.append(origin)
    return result


# The production React frontend on Render. Keep this explicit fallback so a
# missing/incorrect Render environment variable cannot silently break login.
# If you change the frontend's Render hostname, update this value or set
# FRONTEND_URL / CORS_ALLOWED_ORIGINS in the backend environment.
DEFAULT_FRONTEND_ORIGIN = "https://emailing-software-1.onrender.com"

# Accept origins from the comma-separated CORS_ALLOWED_ORIGINS environment
# variable, the FRONTEND_URL variable, and the known production frontend.
# This deliberately does NOT use a wildcard: only trusted frontends are allowed.
CORS_ALLOWED_ORIGINS = _unique_origins(
    _origins("CORS_ALLOWED_ORIGINS"),
    _origins("FRONTEND_URL"),
    [DEFAULT_FRONTEND_ORIGIN],
)

# Local Vite development/preview origins are allowed only when DEBUG=True.
if DEBUG:
    CORS_ALLOWED_ORIGINS = _unique_origins(
        CORS_ALLOWED_ORIGINS,
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
    )

CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r"^/api/.*$"
CORS_PREFLIGHT_MAX_AGE = 86400

# CSRF_TRUSTED_ORIGINS also accepts an explicit environment variable. Merge
# rather than overwrite so the deployed frontend remains trusted.
CSRF_TRUSTED_ORIGINS = _unique_origins(
    _origins("CSRF_TRUSTED_ORIGINS"),
    CORS_ALLOWED_ORIGINS,
)

# ---------------------------------------------------------------------------
# REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Authentication
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),

    # Permissions
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),

    # Filtering / searching / ordering
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),

    # Pagination
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardResultsPagination",
    "PAGE_SIZE": 20,

    # Throttling
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),

    "DEFAULT_THROTTLE_RATES": {
        "test-email": "10/hour",
        "webhook": "600/minute",
        "auth": "20/minute",
        "cron": "120/minute",
        # NEW (Signup Forms feature) — per-IP limits on the two public,
        # unauthenticated signup-form endpoints (see signup_forms/views.py).
        # "signup-form" (viewing a form) is looser than "signup-form-submit"
        # (actually creating/updating a contact), matching how a page load
        # naturally happens more often than a form submit.
        "signup-form": "120/minute",
        "signup-form-submit": "20/minute",
        # NEW (Marketing Automation) — external event intake (POST /api/automations/events/)
        "automation-events": "120/minute",
    },

    # Exception handling
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",

    # Renderer
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
}


# ---------------------------------------------------------------------------
# Simple JWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(
            os.getenv(
                "ACCESS_TOKEN_LIFETIME_MINUTES",
                30,
            )
        )
    ),

    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(
            os.getenv(
                "REFRESH_TOKEN_LIFETIME_DAYS",
                7,
            )
        )
    ),

    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,

    "AUTH_HEADER_TYPES": ("Bearer",),

    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}


# ---------------------------------------------------------------------------
# Brevo
# ---------------------------------------------------------------------------
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_API_BASE_URL = os.getenv(
    "BREVO_API_BASE_URL",
    "https://api.brevo.com/v3",
)

BREVO_WEBHOOK_SECRET = os.getenv("BREVO_WEBHOOK_SECRET", "")

BREVO_SENDER_NAME = os.getenv(
    "BREVO_SENDER_NAME",
    "Email Campaign Platform",
)

BREVO_SENDER_EMAIL = os.getenv(
    "BREVO_SENDER_EMAIL",
    "no-reply@example.com",
)
# The test runner never talks to Brevo (tests mock the client); a placeholder key lets the
# provider readiness check pass without real credentials. Never used outside `manage.py test`.
if "test" in sys.argv and not BREVO_API_KEY:
    BREVO_API_KEY = "test-placeholder-not-a-real-key"
BREVO_MAX_SEND_ATTEMPTS = int(os.getenv("BREVO_MAX_SEND_ATTEMPTS", "2"))


# ---------------------------------------------------------------------------
# Email provider selection + self-hosted SMTP (Postfix)  (NEW)
# ---------------------------------------------------------------------------
# EMAIL_PROVIDER is the fallback when PlatformSettings.active_provider is unset.
# Default "brevo" == the exact pre-upgrade behaviour.
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "brevo").strip().lower()
# Use EITHER STARTTLS (port 587, SMTP_USE_TLS=True) OR implicit TLS (port 465,
# SMTP_USE_SSL=True) -- enabling both is rejected as a configuration error.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")          # secret: server-side only
SMTP_USE_TLS = env_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL = env_bool("SMTP_USE_SSL", False)
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "20"))
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO", "")
# Software-side submission cap (messages/minute) used when PlatformSettings.rate_per_minute is
# unset. Must reflect the HOST'S written authorization, not a hoped-for number. 0 = no cap.
SMTP_RATE_LIMIT = int(os.getenv("SMTP_RATE_LIMIT", "0"))
SMTP_MAX_RETRIES = int(os.getenv("SMTP_MAX_RETRIES", "3"))
# Domain whose MX points at the bounce receiver (VERP return-paths). Blank = disabled.
SMTP_BOUNCE_DOMAIN = os.getenv("SMTP_BOUNCE_DOMAIN", "")
# Shared secret the bounce-forwarder on the SMTP server signs requests with (HMAC-SHA256).
SMTP_BOUNCE_WEBHOOK_SECRET = os.getenv("SMTP_BOUNCE_WEBHOOK_SECRET", "")


# ---------------------------------------------------------------------------
# Scheduling / Cron
# ---------------------------------------------------------------------------
# Shared secret guarding POST /api/scheduling/process-due/ — the HTTP
# equivalent of `python manage.py process_scheduled_campaigns`, for hosts
# without real cron access (e.g. a free-tier PaaS), triggered by a free
# external scheduler such as cron-job.org. Required in production; leaving
# it unset only works while DEBUG=True (local development).
CRON_SECRET = os.getenv("CRON_SECRET", "")

# ---------------------------------------------------------------------------
# Marketing Automation (NEW) — all optional, sensible defaults
# ---------------------------------------------------------------------------
# Max automation steps processed per /api/scheduling/process-due/ call, and a wall-clock budget
# (seconds) so a run stays well under gunicorn's --timeout 30. Anything left over is simply picked
# up by the next cron tick.
AUTOMATION_BATCH_SIZE = int(os.getenv("AUTOMATION_BATCH_SIZE", "50"))
AUTOMATION_RUN_TIME_BUDGET_SECONDS = int(os.getenv("AUTOMATION_RUN_TIME_BUDGET_SECONDS", "20"))
# A claimed enrollment older than this is treated as abandoned by a crashed worker.
AUTOMATION_LOCK_LEASE_SECONDS = int(os.getenv("AUTOMATION_LOCK_LEASE_SECONDS", "300"))
# A failed step is retried up to this many attempts, waiting RETRY_DELAY_MINUTES * attempt between.
AUTOMATION_MAX_STEP_ATTEMPTS = int(os.getenv("AUTOMATION_MAX_STEP_ATTEMPTS", "3"))
AUTOMATION_RETRY_DELAY_MINUTES = int(os.getenv("AUTOMATION_RETRY_DELAY_MINUTES", "15"))
# Run a zero-delay first step right after a signup commits (set False to leave it all to cron).
AUTOMATION_RUN_FIRST_STEP_INLINE = env_bool("AUTOMATION_RUN_FIRST_STEP_INLINE", True)

# How many recipients a single call to campaigns.services.send_campaign_now()
# will actually send, per campaign. Chosen with real headroom under
# gunicorn's --timeout 30 (see the startCommand in render.yaml) — each
# recipient is one live Brevo API call (plus possible retries on transient
# failures), so this bounds a single call/cron-tick to a duration that
# comfortably won't get killed mid-batch. A campaign with more recipients
# than this simply sends across multiple cron ticks instead of one — see
# campaigns/services.py's module docstring and resume_stuck_campaigns().
CAMPAIGN_SEND_BATCH_SIZE = int(os.getenv("CAMPAIGN_SEND_BATCH_SIZE", "20"))


# ---------------------------------------------------------------------------
# Frontend / Backend URLs
# ---------------------------------------------------------------------------
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:5173",
)

# Public base URL of THIS backend, used to build absolute links that must be
# reachable from outside AND from contexts with no HTTP request to derive a
# host from (e.g. the unsubscribe link embedded in an email sent by a
# scheduled/background job -- see brevo/services.py). In local dev this
# stays http://localhost:8000. In production, set this to your real API
# domain.
#
# NOTE: the uploaded-template-image URL (email_templates/views.py) does NOT
# use this anymore -- it derives its URL from the actual incoming request
# instead, so a forgotten/incorrect BACKEND_BASE_URL can no longer break
# inserted images the way it used to.
BACKEND_BASE_URL = os.getenv(
    "BACKEND_BASE_URL",
    "http://localhost:8000",
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },

    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },

    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },

        "brevo": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },

        "campaigns": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },

        "scheduling": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Optional Celery / Redis (NEW). Leave CELERY_BROKER_URL blank to keep cron-driven processing.
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")          # e.g. redis://:password@127.0.0.1:6379/0
CELERY_RESULT_BACKEND = None                                      # results are not needed; the DB is the record
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 300
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "process-due": {"task": "mailflow.process_due", "schedule": 60.0},
    "reconcile-quota": {"task": "mailflow.reconcile_quota", "schedule": 600.0},
    "smtp-health": {"task": "mailflow.smtp_health", "schedule": 300.0},
    "review-stuck": {"task": "mailflow.review_stuck", "schedule": 300.0},
}


# ---------------------------------------------------------------------------
# Invitation / password-reset emails and soft-bounce escalation
# ---------------------------------------------------------------------------
# Invitation and password-reset links are emailed through Brevo's transactional API when it is
# configured (BREVO_API_KEY + BREVO_SENDER_EMAIL). They never use campaign quota. Disabled during tests.
SEND_INVITE_EMAILS = env_bool("SEND_INVITE_EMAILS", True) and "test" not in sys.argv

# A soft bounce is temporary. If an address soft-bounces this many times in a row (no successful
# delivery event in between) within the window, it is suppressed so we stop sending to it.
SOFT_BOUNCE_SUPPRESS_THRESHOLD = int(os.getenv("SOFT_BOUNCE_SUPPRESS_THRESHOLD", "3"))   # 0 disables escalation
SOFT_BOUNCE_WINDOW_DAYS = int(os.getenv("SOFT_BOUNCE_WINDOW_DAYS", "30"))


# ---------------------------------------------------------------------------
# Production hardening (only when DEBUG is False)
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    # Set > 0 only once HTTPS works everywhere (e.g. 31536000); it is sticky in browsers.
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
    # Off by default: platforms like Render terminate TLS at the proxy and health-check over HTTP.
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)


# ---------------------------------------------------------------------------
# Self-service company sign-up (creates a Company + its first Company Admin)
# ---------------------------------------------------------------------------
# New companies are placed on a LIMITED trial plan. A company without a plan has no limit at all, so
# sign-up refuses to proceed rather than create one. Edit the plan under Platform -> Plans & quotas.
ALLOW_COMPANY_SIGNUP = env_bool("ALLOW_COMPANY_SIGNUP", True)
TRIAL_PLAN_NAME = os.getenv("TRIAL_PLAN_NAME", "Trial")
TRIAL_DAILY_QUOTA = int(os.getenv("TRIAL_DAILY_QUOTA", "100"))
TRIAL_MONTHLY_QUOTA = int(os.getenv("TRIAL_MONTHLY_QUOTA", "1000"))
TRIAL_MAX_USERS = int(os.getenv("TRIAL_MAX_USERS", "3"))