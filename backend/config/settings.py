"""
Django settings for the Email Campaign Management Platform.
All sensitive/configurable values are pulled from environment variables (.env).
"""
import os
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

# Render sets RENDER_EXTERNAL_HOSTNAME automatically on every web service
# (e.g. "your-app.onrender.com") — trust it without needing to hardcode it
# into ALLOWED_HOSTS/CORS_ALLOWED_ORIGINS by hand.
_render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if _render_hostname:
    ALLOWED_HOSTS.append(_render_hostname)

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
    "common.middleware.RequestTimingMiddleware",
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
# conn_max_age=60 reuses a single database connection across requests within
# the same Gunicorn worker process for up to 60 seconds, instead of paying a
# fresh TCP+TLS+auth handshake to Supabase on every single request — that
# handshake is a meaningful chunk of latency on a request/response cycle
# talking to a remote database, and eliminating it for back-to-back requests
# noticeably helps perceived speed. 60s (rather than a longer-lived pool) is
# deliberately conservative given Render's free tier can put a worker to
# sleep for extended periods, after which a connection would be stale
# anyway — conn_health_checks below handles that case safely by validating
# a reused connection before trusting it, reconnecting if it's gone stale.
# If you connect through Supabase's "Connection pooling" (pgbouncer) host
# rather than the direct host, that's still complementary to this setting,
# not a replacement for it — pgbouncer pools server-side; this setting
# controls whether *Django* bothers reconnecting every request client-side.
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
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
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
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# CORS / CSRF
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

# ---------------------------------------------------------------------------
# REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "accounts.authentication.CustomJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardResultsPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "test-email": "10/hour",
        "webhook": "600/minute",
        "auth": "20/minute",
        "cron": "120/minute",
    },
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("ACCESS_TOKEN_LIFETIME_MINUTES", 30))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("REFRESH_TOKEN_LIFETIME_DAYS", 7))),
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
BREVO_API_BASE_URL = os.getenv("BREVO_API_BASE_URL", "https://api.brevo.com/v3")
BREVO_WEBHOOK_SECRET = os.getenv("BREVO_WEBHOOK_SECRET", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "QRM")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "noreply@example.com")

# Shared secret guarding POST /api/scheduling/process-due/ — the HTTP
# equivalent of `python manage.py process_scheduled_campaigns`, for hosts
# without real cron access (e.g. a free-tier PaaS), triggered by a free
# external scheduler such as cron-job.org. Required in production; leaving
# it unset only works while DEBUG=True (local development).
CRON_SECRET = os.getenv("CRON_SECRET", "")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
# Public base URL of THIS backend, used to build absolute links that must be
# reachable from outside (e.g. the unsubscribe link embedded in sent emails).
# In local dev this stays http://localhost:8000 and unsubscribe links simply
# won't be clickable from outside your machine — that's fine for testing the
# rest of the flow. In production, set this to your real API domain.
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")

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
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "brevo": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "campaigns": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "scheduling": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "common": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}