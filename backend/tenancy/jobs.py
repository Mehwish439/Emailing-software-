"""Heartbeats: let the platform admin see when each scheduled job last ran (cron OR Celery beat)."""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def beat(name, status="ok", detail=""):
    """Best-effort: monitoring must never break the job it observes."""
    try:
        from django.db.models import F

        from .models import JobHeartbeat

        obj, created = JobHeartbeat.objects.get_or_create(
            name=name, defaults={"last_run_at": timezone.now(), "last_status": status, "detail": detail[:300], "runs": 1}
        )
        if not created:
            JobHeartbeat.objects.filter(pk=obj.pk).update(
                last_run_at=timezone.now(), last_status=status, detail=detail[:300], runs=F("runs") + 1
            )
    except Exception:  # noqa: BLE001
        logger.exception("Could not record heartbeat for %s", name)
