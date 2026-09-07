import logging
import zoneinfo

from django.db import transaction
from django.utils import timezone as dj_timezone

from campaigns.models import Campaign
from campaigns.services import validate_campaign_sendable
from common.db import select_for_update_kwargs
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
        ScheduledCampaign.objects.select_for_update(**select_for_update_kwargs())
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
    """
    Sends this schedule's campaign. NOTE: send_campaign_now() only sends one
    bounded batch of recipients per call (see campaigns.services'
    CAMPAIGN_SEND_BATCH_SIZE) -- for a campaign with more recipients than
    that, this schedule will still be PROCESSING (not COMPLETED) when this
    returns, and campaigns.services.resume_stuck_campaigns() (called at the
    end of process_due_schedules(), below) picks up its next batch on every
    subsequent run until it's actually done. That's what makes a large
    campaign resilient to a single request/cron-tick timing out partway
    through -- see campaigns.services._finalize_campaign for where a
    schedule actually gets marked COMPLETED/FAILED, once its campaign
    truly has no PENDING recipients left.
    """
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

    schedule.refresh_from_db()
    result = "sent" if schedule.status == ScheduledCampaign.Status.COMPLETED else "batch_sent"
    return {"schedule_id": schedule.id, "campaign_id": schedule.campaign_id, "result": result}


def process_due_schedules():
    """
    Finds and sends every currently-due ScheduledCampaign, one at a time,
    then continues any campaign (scheduled or "Send Now") still stuck in
    PROCESSING with recipients left PENDING from a previous, cut-off run.
    Returns a list of per-item result dicts:
        {"schedule_id"/"campaign_id": ..., "result": "sent"}
        {"schedule_id"/"campaign_id": ..., "result": "batch_sent"}  -- more batches still to go
        {"schedule_id"/"campaign_id": ..., "result": "failed", "detail": "..."}
    """
    logger.info("process_due_schedules: run started at %s", dj_timezone.now().isoformat())
    results = []
    while True:
        schedule = _claim_next_due_schedule()
        if schedule is None:
            break
        logger.info(
            "process_due_schedules: claimed schedule_id=%s campaign_id=%s scheduled_at=%s",
            schedule.id, schedule.campaign_id, schedule.scheduled_at.isoformat(),
        )
        result = _process_one_schedule(schedule)
        logger.info("process_due_schedules: result=%s", result)
        results.append(result)

    # Resume anything left stuck in PROCESSING with PENDING recipients --
    # e.g. a batch cut off by a request timeout on a previous run of this
    # same function, or a "Send Now" campaign (no ScheduledCampaign row at
    # all) that got cut off mid-request. This is also what safely recovers
    # any campaign that was already stuck before this fix existed: the very
    # next time this runs (cron calls it every minute), it picks them back
    # up automatically.
    from campaigns.services import resume_stuck_campaigns

    resumed = resume_stuck_campaigns()
    for r in resumed:
        logger.info("process_due_schedules: resumed campaign_id=%s -> status=%s", r["campaign_id"], r["status"])
        if r["status"] == Campaign.Status.PROCESSING:
            mapped_result = "batch_sent"
        elif r["status"] == Campaign.Status.SENT:
            mapped_result = "sent"
        else:
            mapped_result = "failed"
        entry = {"campaign_id": r["campaign_id"], "result": mapped_result}
        if mapped_result == "failed":
            entry["detail"] = f"Campaign ended in status '{r['status']}' — see the campaign's failure_reason."
        results.append(entry)

    if not results:
        logger.info(
            "process_due_schedules: no due schedules found (checked scheduled_at <= %s). "
            "If you expected a due campaign here, either nothing is actually calling this function "
            "(see POST /api/scheduling/process-due/ or `manage.py process_scheduled_campaigns` — "
            "one of these needs an external trigger, e.g. Supabase pg_cron or cron-job.org) or the "
            "ScheduledCampaign's status/scheduled_at doesn't match what you expect — check "
            "the ScheduledCampaign row directly.",
            dj_timezone.now().isoformat(),
        )
    else:
        logger.info("process_due_schedules: run finished, processed %s schedule(s)", len(results))
    return results