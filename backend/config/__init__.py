# Celery is optional: the app (and the existing cron-based scheduler) runs fine without it installed.
try:
    from .celery import app as celery_app  # noqa: F401

    __all__ = ("celery_app",)
except ImportError:  # pragma: no cover
    pass
