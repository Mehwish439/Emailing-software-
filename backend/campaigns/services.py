"""
Campaign business logic. Views (and the process_scheduled_campaigns
management command) call these functions; these functions call
brevo/services.py for anything that talks to the Brevo API. No Brevo logic
or raw DB queries belong directly in views.py.

Sending is synchronous: there is no task queue in this architecture. Both
"send now" (via the API) and scheduled sends (via the cron-driven
process_scheduled_campaigns command) call send_campaign_now(), which blocks
until every recipient has been attempted. For an MVP campaign platform this
keeps the architecture simple (no Redis/Celery); if campaign sizes grow large
enough that this becomes too slow for an HTTP request, "send now" is the only
caller in the request/response path — scheduled sends already run out-of-band
via cron, so they're unaffected by that concern.
"""
import logging

from django.db import transaction
from django.utils import timezone

from common.exceptions import BrevoAPIError, ValidationAppError
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
    campaign = Campaign.objects.select_for_update().get(id=campaign_id)
    validate_campaign_sendable(campaign)
    build_recipient_snapshot(campaign)
    campaign.status = Campaign.Status.PROCESSING
    campaign.save(update_fields=["status", "updated_at"])
    return campaign


def _send_pending_recipients(campaign: Campaign):
    """
    Synchronously sends the campaign to every PENDING recipient via Brevo.
    Retries a small, fixed number of times on transient BrevoAPIError before
    marking that individual recipient FAILED and moving on — one recipient's
    failure never aborts the rest of the send.
    """
    from brevo.services import send_to_recipient

    pending = campaign.recipients.filter(status=CampaignRecipient.Status.PENDING).select_related("contact")

    for recipient in pending:
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


def _finalize_campaign(campaign: Campaign):
    """Marks the campaign SENT once sending is done, or FAILED if every recipient failed."""
    campaign.refresh_from_db()
    if campaign.status != Campaign.Status.PROCESSING:
        return  # already finalized/cancelled by something else

    recipients = campaign.recipients.all()
    total = recipients.count()
    failed = recipients.filter(status=CampaignRecipient.Status.FAILED).count()

    if total == 0:
        mark_campaign_failed(campaign, "No eligible recipients at send time.")
    elif failed == total:
        mark_campaign_failed(campaign, "All recipient sends failed.")
    else:
        mark_campaign_sent(campaign)


def send_campaign_now(campaign: Campaign):
    """
    Sends a campaign immediately and synchronously. Used by both the
    "Send Now" API endpoint and scheduling's process_scheduled_campaigns
    management command — the single place campaign-sending logic lives, so
    neither caller duplicates it.
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