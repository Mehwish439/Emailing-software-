"""
Celery tasks. Each one is a thin wrapper over the SAME service function the cron entry point
calls, so behaviour is identical whichever scheduler drives it. Overlapping runs are safe:
campaign claiming uses row locks, every message has a unique idempotency key, and quota
reservation is transactional -- a second worker simply finds nothing left to do.
"""
import logging

from celery import shared_task

from tenancy.jobs import beat

logger = logging.getLogger(__name__)


@shared_task(name="mailflow.process_due")
def process_due():
    """Scheduled campaigns + resume in-flight batches + due automation steps (every minute)."""
    from scheduling.services import process_due_automation_steps, process_due_schedules

    try:
        results = process_due_schedules()
        automations = process_due_automation_steps()
    except Exception as exc:  # noqa: BLE001
        beat("process_due", "error", str(exc))
        raise
    beat("process_due", "ok", f"{len(results)} campaign item(s); automations sent={automations.get('sent', 0)}")
    return len(results)


@shared_task(name="mailflow.reconcile_quota")
def reconcile_quota():
    """Repair any quota-ledger drift (e.g. a crash between 'provider accepted' and 'credit consumed')."""
    from tenancy.quota import reconcile

    fixed = reconcile()
    beat("reconcile_quota", "ok", f"consumed+{fixed['consumed']} released+{fixed['released']}")
    return fixed


@shared_task(name="mailflow.smtp_health")
def smtp_health():
    """Probe the SMTP server (connect + authenticate only; NEVER sends mail) and record the result."""
    from django.conf import settings

    from .smtp_provider import SmtpProvider
    from tenancy.models import PlatformSettings

    if not settings.SMTP_HOST and PlatformSettings.load().active_provider != "smtp":
        return None
    health = SmtpProvider().health()
    beat("smtp_health", "ok" if health["ok"] else "error", health.get("detail", ""))
    return health["ok"]


@shared_task(name="mailflow.review_stuck")
def review_stuck():
    """Surface abandoned SUBMITTING claims as needs_review (they are never auto-resent)."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import OutboundMessage

    n = OutboundMessage.objects.filter(
        state="submitting", submitting_since__lt=timezone.now() - timedelta(minutes=10)
    ).update(state="needs_review", last_error="Submission never reported a result; may or may not have been sent.")
    beat("review_stuck", "ok", f"{n} flagged")
    return n
