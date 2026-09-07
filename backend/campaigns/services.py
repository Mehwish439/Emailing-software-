"""
Campaign business logic. Views (and the process_scheduled_campaigns
management command) call these functions; these functions call
brevo/services.py for anything that talks to the Brevo API. No Brevo logic
or raw DB queries belong directly in views.py.

Sending is synchronous and BATCHED: there is no task queue in this
architecture, and Render's gunicorn is configured with --timeout 30, which
will hard-kill any single request running longer than that (see
render.yaml). A campaign with more recipients than fit in that window
(each Brevo API call + DB write takes real time) would previously get cut
off mid-send, leaving it stuck in PROCESSING forever with the remaining
recipients still PENDING -- see resume_stuck_campaigns() below for how
that's now recovered.

So instead of sending every recipient in one call, send_campaign_now()
sends up to CAMPAIGN_SEND_BATCH_SIZE recipients per call and returns,
leaving the campaign in PROCESSING if any are still PENDING.
scheduling.services.process_due_schedules() (triggered every minute by
cron/an external pinger -- see scheduling/views.py) calls
resume_stuck_campaigns() on every run specifically to keep sending a large
campaign's remaining batches, in addition to starting newly-due schedules.
This is also what safely resumes any campaign already stuck in PROCESSING
from before this fix existed, automatically, without a one-off script.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.db import select_for_update_kwargs
from common.exceptions import BrevoAPIError, ValidationAppError
from contacts.models import Suppression
from contacts.services_suppression import filter_out_suppressed

from .models import Campaign, CampaignRecipient

logger = logging.getLogger(__name__)

# How many times to retry a single recipient send on a transient Brevo error
# before marking that recipient FAILED. Kept small and synchronous — there's
# no task queue to hand retries off to.
MAX_SEND_ATTEMPTS = 2


def validate_campaign_sendable(campaign: Campaign):
    """Raises ValidationAppError if the campaign is not in a sendable state."""
    if campaign.status not in (Campaign.Status.DRAFT, Campaign.Status.SCHEDULED, Campaign.Status.FAILED):
        raise ValidationAppError(f"Campaign cannot be sent while in '{campaign.status}' status.")
    if not campaign.template_id:
        raise ValidationAppError("Campaign must have a template.")
    if not campaign.sender_email:
        raise ValidationAppError("Campaign must have a sender email.")
    if not campaign.contact_lists.exists():
        raise ValidationAppError("Campaign must have at least one contact list selected.")
    if not campaign.eligible_contacts_queryset().exists():
        raise ValidationAppError("Campaign has no eligible (non-suppressed, active) recipients.")


def build_recipient_snapshot(campaign: Campaign):
    """
    Creates/refreshes CampaignRecipient rows for every eligible contact,
    filtering out suppressed emails. Idempotent — existing recipient rows
    for still-eligible contacts are left untouched.
    """
    eligible_contacts = campaign.eligible_contacts_queryset()
    existing_contact_ids = set(campaign.recipients.values_list("contact_id", flat=True))
    new_rows = [
        CampaignRecipient(campaign=campaign, contact=contact)
        for contact in eligible_contacts
        if contact.id not in existing_contact_ids
    ]
    if new_rows:
        CampaignRecipient.objects.bulk_create(new_rows, ignore_conflicts=True)
    return campaign.recipients.count()


@transaction.atomic
def _claim_campaign_for_sending(campaign_id):
    """
    Locks the Campaign row (SELECT ... FOR UPDATE where the backend supports
    it — e.g. Postgres/Supabase; a no-op lock on SQLite) so that two
    concurrent callers (e.g. a "send now" API request racing a cron-driven
    scheduled send for the same campaign) cannot both claim it. Validates,
    snapshots recipients, and flips status to PROCESSING inside the same
    transaction so the claim is atomic.
    """
    # No skip_locked here (unlike the resume/schedule-claim queries below) --
    # this targets one specific known row by ID, so a concurrent claim
    # should briefly wait for the lock and then correctly fail
    # validate_campaign_sendable() (status will have moved on), not skip
    # itself and raise DoesNotExist.
    campaign = Campaign.objects.select_for_update().get(id=campaign_id)
    validate_campaign_sendable(campaign)
    build_recipient_snapshot(campaign)
    campaign.status = Campaign.Status.PROCESSING
    campaign.save(update_fields=["status", "updated_at"])
    return campaign


def _send_pending_recipients(campaign: Campaign):
    """
    Sends up to CAMPAIGN_SEND_BATCH_SIZE PENDING recipients via Brevo (not
    necessarily all of them — see the module docstring for why). Retries a
    small, fixed number of times on transient BrevoAPIError before marking
    that individual recipient FAILED and moving on — one recipient's
    failure never aborts the rest of the batch.

    Safe to call again on the same campaign for its next batch: it always
    re-queries for whatever's still PENDING, so recipients already marked
    SENT/FAILED by a previous batch are simply never selected again — this
    is what keeps resumed batches from ever double-sending someone.

    Re-checks suppression here, not just at snapshot time
    (build_recipient_snapshot / eligible_contacts_queryset): a
    CampaignRecipient row can sit PENDING for a long time (a scheduled
    campaign waiting for its send time, or a batch waiting for its next
    cron tick) and the contact can become suppressed (hard bounce, spam
    complaint, unsubscribe) on a DIFFERENT campaign in the meantime. Without
    this second check, that stale PENDING row would still get sent —
    exactly what happened with a contact that hard-bounced on one campaign
    and was then still mailed by another, already-snapshotted campaign a
    couple of days later.
    """
    from brevo.services import send_to_recipient

    pending = list(
        campaign.recipients.filter(status=CampaignRecipient.Status.PENDING)
        .select_related("contact")
        .order_by("id")[: settings.CAMPAIGN_SEND_BATCH_SIZE]
    )
    if not pending:
        return

    batch_emails = {r.contact.email for r in pending}
    suppressed_emails = set(
        Suppression.objects.filter(email__in=batch_emails).values_list("email", flat=True)
    )

    for recipient in pending:
        if recipient.contact.email in suppressed_emails:
            logger.info(
                "Skipping recipient=%s (%s) for campaign=%s — contact was suppressed after this "
                "campaign's recipient snapshot was taken.",
                recipient.id, recipient.contact.email, campaign.id,
            )
            # BLOCKED is the closest existing status for "deliberately not
            # sent because they're suppressed" — matches the same word Brevo
            # itself uses when its own blocklist stops a send.
            recipient.status = CampaignRecipient.Status.BLOCKED
            recipient.save(update_fields=["status", "updated_at"])
            continue

        last_error = None
        for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
            try:
                send_to_recipient(campaign, recipient)
                last_error = None
                break
            except BrevoAPIError as exc:
                last_error = exc
                logger.warning(
                    "Brevo send failed for recipient=%s (attempt %s/%s): %s",
                    recipient.id, attempt, MAX_SEND_ATTEMPTS, exc,
                )

        if last_error is not None:
            recipient.status = CampaignRecipient.Status.FAILED
            recipient.save(update_fields=["status", "updated_at"])
            continue

        recipient.status = CampaignRecipient.Status.SENT
        recipient.sent_at = timezone.now()
        recipient.save(update_fields=["status", "sent_at", "updated_at"])


def _sync_schedule_on_finalize(campaign: Campaign):
    """
    If this campaign was started via a schedule (scheduling.models.
    ScheduledCampaign), reflects the campaign's now-final status onto that
    schedule row too -- this is the piece that was missing before: a
    campaign could reach SENT/FAILED while its schedule stayed at
    PROCESSING forever, which is exactly why the scheduler kept reporting
    "no due schedules found" even with a campaign still (invisibly) needing
    attention. Local import avoids a circular import (scheduling already
    imports from campaigns).
    """
    from scheduling.models import ScheduledCampaign

    schedule = getattr(campaign, "schedule", None)
    if schedule is None or schedule.status != ScheduledCampaign.Status.PROCESSING:
        return

    if campaign.status == Campaign.Status.SENT:
        schedule.status = ScheduledCampaign.Status.COMPLETED
        schedule.completed_at = timezone.now()
        schedule.save(update_fields=["status", "completed_at", "updated_at"])
    elif campaign.status == Campaign.Status.FAILED:
        schedule.status = ScheduledCampaign.Status.FAILED
        schedule.error_message = campaign.failure_reason
        schedule.save(update_fields=["status", "error_message", "updated_at"])


def _finalize_campaign(campaign: Campaign):
    """
    Marks the campaign SENT once every recipient has reached a terminal
    state (sent or failed), or FAILED if every recipient failed. If any
    recipients are still PENDING -- because _send_pending_recipients only
    processes one bounded batch per call -- the campaign is deliberately
    left in PROCESSING so the next run (see resume_stuck_campaigns) sends
    the remaining batch, instead of being incorrectly marked done early.
    """
    campaign.refresh_from_db()
    if campaign.status != Campaign.Status.PROCESSING:
        return  # already finalized/cancelled by something else

    recipients = campaign.recipients.all()
    pending_count = recipients.filter(status=CampaignRecipient.Status.PENDING).count()
    if pending_count > 0:
        return  # more batches still to go — leave PROCESSING for the next run

    total = recipients.count()
    failed = recipients.filter(status=CampaignRecipient.Status.FAILED).count()

    if total == 0:
        mark_campaign_failed(campaign, "No eligible recipients at send time.")
    elif failed == total:
        mark_campaign_failed(campaign, "All recipient sends failed.")
    else:
        mark_campaign_sent(campaign)

    _sync_schedule_on_finalize(campaign)


def _claim_stuck_campaign_for_resume(campaign_id):
    """
    Mirrors _claim_campaign_for_sending's row-locking, but for a campaign
    that's already PROCESSING (started by a previous batch) rather than one
    being started for the first time -- so two overlapping cron runs can
    never grab the same campaign's next batch at once. skip_locked here is
    correct (unlike _claim_campaign_for_sending above): this is scanning
    for "any of several stuck campaigns", so one already locked by a
    concurrent run should just be skipped this pass, not waited on. Returns
    None if the campaign isn't actually still processing/available (already
    finished or claimed by a concurrent run).
    """
    with transaction.atomic():
        return (
            Campaign.objects.select_for_update(**select_for_update_kwargs())
            .filter(id=campaign_id, status=Campaign.Status.PROCESSING)
            .first()
        )


def resume_stuck_campaigns():
    """
    Continues sending any campaign left in PROCESSING with recipients still
    PENDING -- whether it originally started via "Send Now" (cut off
    mid-HTTP-request) or a schedule (cut off mid cron-triggered batch). Call
    this on every cron tick (see scheduling.services.process_due_schedules)
    alongside picking up newly-due schedules, so a large campaign's send
    survives request timeouts by spreading across as many calls as it
    needs -- each sends up to CAMPAIGN_SEND_BATCH_SIZE more, and the
    campaign finalizes itself (see _finalize_campaign) the moment nothing
    PENDING is left. This is also the recovery path for any campaign
    already stuck in PROCESSING from before this fix existed.

    Returns a list of {"campaign_id": ..., "status": <new campaign status>}.
    """
    stuck_ids = list(
        Campaign.objects.filter(
            status=Campaign.Status.PROCESSING,
            recipients__status=CampaignRecipient.Status.PENDING,
        )
        .distinct()
        .values_list("id", flat=True)
    )

    results = []
    for campaign_id in stuck_ids:
        campaign = _claim_stuck_campaign_for_resume(campaign_id)
        if campaign is None:
            continue  # finished, or already being resumed by a concurrent run
        logger.info("resume_stuck_campaigns: sending next batch for campaign_id=%s", campaign.id)
        _send_pending_recipients(campaign)
        _finalize_campaign(campaign)
        campaign.refresh_from_db()
        results.append({"campaign_id": campaign.id, "status": campaign.status})
    return results


def send_campaign_now(campaign: Campaign):
    """
    Claims the campaign and sends its first batch (up to
    CAMPAIGN_SEND_BATCH_SIZE recipients) immediately and synchronously. Used
    by both the "Send Now" API endpoint and scheduling's
    process_scheduled_campaigns command/process-due endpoint — the single
    place campaign-sending logic lives, so neither caller duplicates it.

    For a campaign with more recipients than one batch, the returned
    campaign will still have status PROCESSING — that's expected, not an
    error; scheduling.services.process_due_schedules() (cron-driven, every
    minute) will keep calling resume_stuck_campaigns() until it's SENT.
    """
    campaign = _claim_campaign_for_sending(campaign.id)
    _send_pending_recipients(campaign)
    _finalize_campaign(campaign)
    campaign.refresh_from_db()
    return campaign


def mark_campaign_sent(campaign: Campaign):
    campaign.status = Campaign.Status.SENT
    campaign.sent_at = timezone.now()
    campaign.save(update_fields=["status", "sent_at", "updated_at"])


def mark_campaign_failed(campaign: Campaign, reason: str):
    campaign.status = Campaign.Status.FAILED
    campaign.failure_reason = reason[:2000]
    campaign.save(update_fields=["status", "failure_reason", "updated_at"])