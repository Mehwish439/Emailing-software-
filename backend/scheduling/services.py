import logging
import zoneinfo

from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from campaigns.models import Campaign
from campaigns.services import validate_campaign_sendable
from common.exceptions import ValidationAppError

from .models import ScheduledCampaign

logger = logging.getLogger(__name__)


def validate_timezone(tz_name: str):
    try:
        zoneinfo.ZoneInfo(tz_name)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise ValidationAppError(f"'{tz_name}' is not a recognized timezone.") from exc


def validate_schedule_time(scheduled_at):
    if scheduled_at <= dj_timezone.now():
        raise ValidationAppError("Scheduled time must be in the future.")


def create_schedule(campaign: Campaign, scheduled_at, timezone_name: str):
    """
    Creates (or replaces) a schedule for a campaign. No task is enqueued here
    — there is no task queue in this architecture. The scheduled_at timestamp
    is simply persisted (in UTC); the process_scheduled_campaigns management
    command, run periodically by cron, is what actually picks it up and sends
    it once due. See scheduling/management/commands/process_scheduled_campaigns.py.
    """
    if campaign.status == Campaign.Status.SENT:
        raise ValidationAppError("This campaign has already been sent and cannot be scheduled.")
    if hasattr(campaign, "schedule") and campaign.schedule.status == ScheduledCampaign.Status.SCHEDULED:
        raise ValidationAppError("This campaign already has an active schedule. Cancel it before creating a new one.")

    validate_timezone(timezone_name)
    validate_schedule_time(scheduled_at)
    validate_campaign_sendable(campaign)

    schedule, _ = ScheduledCampaign.objects.update_or_create(
        campaign=campaign,
        defaults={
            "scheduled_at": scheduled_at,
            "timezone": timezone_name,
            "status": ScheduledCampaign.Status.SCHEDULED,
            "error_message": "",
            "cancelled_at": None,
            "completed_at": None,
            "started_at": None,
        },
    )
    campaign.status = Campaign.Status.SCHEDULED
    campaign.save(update_fields=["status", "updated_at"])
    return schedule


def update_schedule(schedule: ScheduledCampaign, scheduled_at=None, timezone_name=None):
    """Reschedules a still-pending ScheduledCampaign to a new time/timezone."""
    if schedule.status != ScheduledCampaign.Status.SCHEDULED:
        raise ValidationAppError("Only campaigns with a pending schedule can be rescheduled.")

    new_time = scheduled_at or schedule.scheduled_at
    new_tz = timezone_name or schedule.timezone
    validate_timezone(new_tz)
    validate_schedule_time(new_time)

    schedule.scheduled_at = new_time
    schedule.timezone = new_tz
    schedule.save(update_fields=["scheduled_at", "timezone", "updated_at"])
    return schedule


def cancel_schedule(schedule: ScheduledCampaign):
    """Cancels a pending schedule and returns the campaign to draft."""
    if schedule.status != ScheduledCampaign.Status.SCHEDULED:
        raise ValidationAppError("Only a pending schedule can be cancelled.")

    schedule.status = ScheduledCampaign.Status.CANCELLED
    schedule.cancelled_at = dj_timezone.now()
    schedule.save(update_fields=["status", "cancelled_at", "updated_at"])

    schedule.campaign.status = Campaign.Status.DRAFT
    schedule.campaign.save(update_fields=["status", "updated_at"])
    return schedule


# ---------------------------------------------------------------------------
# Due-schedule processing — the actual cron/HTTP-trigger entry point.
#
# This is called from two places:
#   - scheduling/management/commands/process_scheduled_campaigns.py, for a
#     real cron / VPS / Render Cron Job setup
#   - scheduling/views.py's process_due_schedules_view (POST /api/scheduling/
#     process-due/), for hosts without real cron access — e.g. a free-tier
#     PaaS web service pinged by a free external scheduler like cron-job.org
# Both are equally safe to call concurrently or repeatedly; see the
# claim-then-lock logic below.
# ---------------------------------------------------------------------------

def _select_for_update_kwargs():
    """SKIP LOCKED only where the DB backend actually supports it (e.g. Postgres/Supabase)."""
    if connection.features.has_select_for_update_skip_locked:
        return {"skip_locked": True}
    return {}


@transaction.atomic
def _claim_next_due_schedule():
    """
    Atomically finds, locks, and claims exactly one due ScheduledCampaign.
    Two concurrent callers (overlapping cron runs, or a cron run racing an
    HTTP-triggered run) can never claim the same row — see SELECT ... FOR
    UPDATE SKIP LOCKED discussion in process_scheduled_campaigns.py's
    module docstring. Returns None when nothing is due.
    """
    schedule = (
        ScheduledCampaign.objects.select_for_update(**_select_for_update_kwargs())
        .select_related("campaign")
        .filter(status=ScheduledCampaign.Status.SCHEDULED, scheduled_at__lte=dj_timezone.now())
        .order_by("scheduled_at")
        .first()
    )
    if schedule is None:
        return None

    schedule.status = ScheduledCampaign.Status.PROCESSING
    schedule.started_at = dj_timezone.now()
    schedule.save(update_fields=["status", "started_at", "updated_at"])
    return schedule


def _mark_schedule_failed(schedule, message):
    schedule.status = ScheduledCampaign.Status.FAILED
    schedule.error_message = message
    schedule.save(update_fields=["status", "error_message", "updated_at"])


def _process_one_schedule(schedule):
    from campaigns.services import send_campaign_now

    try:
        send_campaign_now(schedule.campaign)
    except ValidationAppError as exc:
        _mark_schedule_failed(schedule, str(exc))
        return {"schedule_id": schedule.id, "campaign_id": schedule.campaign_id, "result": "failed", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one bad schedule must never abort the whole run
        logger.exception("Unexpected error processing schedule %s", schedule.id)
        detail = str(exc)[:2000]
        _mark_schedule_failed(schedule, detail)
        return {"schedule_id": schedule.id, "campaign_id": schedule.campaign_id, "result": "failed", "detail": detail}

    schedule.status = ScheduledCampaign.Status.COMPLETED
    schedule.completed_at = dj_timezone.now()
    schedule.save(update_fields=["status", "completed_at", "updated_at"])
    return {"schedule_id": schedule.id, "campaign_id": schedule.campaign_id, "result": "sent"}


def process_due_schedules():
    """
    Finds and sends every currently-due ScheduledCampaign, one at a time.
    Returns a list of per-schedule result dicts:
        {"schedule_id": ..., "campaign_id": ..., "result": "sent"}
        {"schedule_id": ..., "campaign_id": ..., "result": "failed", "detail": "..."}
    """
    results = []
    while True:
        schedule = _claim_next_due_schedule()
        if schedule is None:
            break
        results.append(_process_one_schedule(schedule))
    return results