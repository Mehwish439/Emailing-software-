"""
Processes inbound Brevo webhook events.

Brevo's webhook payloads vary slightly by event but generally include:
  event: "delivered" | "opened" | "click" | "soft_bounce" | "hard_bounce" |
         "blocked" | "spam" | "unsubscribed" | ...
  email: recipient email address
  message-id / messageId: the transactional message id
  date / ts: event timestamp
  tags: list of tags we sent (contains "campaign-<id>")

We identify the campaign either from the X-Campaign-Id / X-Recipient-Id
metadata we set when sending, or by parsing the "campaign-<id>" tag.
Idempotency is enforced with a `dedupe_key` unique constraint built from
message-id + event type (falls back to email+event+timestamp if no message id).
"""
import logging
import re

from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive, make_aware

from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact
from contacts.services_suppression import add_suppression

logger = logging.getLogger(__name__)

# Maps Brevo's event names to our internal enums.
EVENT_MAP = {
    "delivered": "delivered",
    "opened": "opened",
    "unique_opened": "opened",
    "click": "clicked",
    "clicked": "clicked",
    "soft_bounce": "soft_bounce",
    "hard_bounce": "hard_bounce",
    "blocked": "blocked",
    "spam": "spam",
    "unsubscribed": "unsubscribed",
    "invalid_email": "hard_bounce",
}

RECIPIENT_STATUS_MAP = {
    "delivered": CampaignRecipient.Status.DELIVERED,
    "opened": CampaignRecipient.Status.OPENED,
    "clicked": CampaignRecipient.Status.CLICKED,
    "soft_bounce": CampaignRecipient.Status.BOUNCED,
    "hard_bounce": CampaignRecipient.Status.BOUNCED,
    "blocked": CampaignRecipient.Status.BLOCKED,
    "spam": CampaignRecipient.Status.SPAM,
    "unsubscribed": CampaignRecipient.Status.UNSUBSCRIBED,
}

SUPPRESSION_REASON_MAP = {
    "hard_bounce": "hard_bounce",
    "blocked": "blocked",
    "spam": "spam_complaint",
    "unsubscribed": "unsubscribed",
}

CAMPAIGN_TAG_RE = re.compile(r"campaign-(\d+)")


class WebhookProcessingError(Exception):
    pass


def _extract_campaign_id(payload):
    headers = payload.get("headers") or {}
    if headers.get("X-Campaign-Id"):
        try:
            return int(headers["X-Campaign-Id"])
        except (TypeError, ValueError):
            pass
    for tag in payload.get("tags", []) or []:
        match = CAMPAIGN_TAG_RE.search(str(tag))
        if match:
            return int(match.group(1))
    return None


def _extract_recipient_id(payload):
    headers = payload.get("headers") or {}
    value = headers.get("X-Recipient-Id")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _extract_timestamp(payload):
    raw = payload.get("date") or payload.get("ts_event") or payload.get("ts")
    if raw is None:
        from django.utils import timezone

        return timezone.now()
    if isinstance(raw, (int, float)):
        from datetime import datetime, timezone as dt_timezone

        return datetime.fromtimestamp(raw, tz=dt_timezone.utc)
    parsed = parse_datetime(str(raw))
    if parsed is None:
        from django.utils import timezone

        return timezone.now()
    if is_naive(parsed):
        parsed = make_aware(parsed)
    return parsed


def process_webhook_event(payload: dict):
    """
    Processes a single Brevo webhook event payload.
    Returns a short string describing the outcome (for logging/testing).
    Idempotent: calling this twice with the same message-id + event is a no-op
    the second time.
    """
    from analytics.models import CampaignEvent

    brevo_event = (payload.get("event") or "").strip().lower()
    internal_event = EVENT_MAP.get(brevo_event)
    if internal_event is None:
        logger.info("Ignoring unhandled Brevo event type: %s", brevo_event)
        return "ignored-unhandled-event"

    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise WebhookProcessingError("Webhook payload missing recipient email.")

    message_id = payload.get("message-id") or payload.get("messageId") or ""
    dedupe_key = f"{message_id}:{internal_event}" if message_id else f"{email}:{internal_event}:{payload.get('date', '')}"

    if CampaignEvent.objects.filter(dedupe_key=dedupe_key).exists():
        return "duplicate-ignored"

    campaign_id = _extract_campaign_id(payload)
    campaign = Campaign.objects.filter(id=campaign_id).first() if campaign_id else None
    if campaign is None:
        logger.warning("Webhook event for unknown/missing campaign_id=%s email=%s", campaign_id, email)
        return "ignored-unknown-campaign"

    contact = Contact.objects.filter(owner=campaign.created_by, email__iexact=email).first()
    if contact is None:
        logger.warning("Webhook event for unknown contact email=%s under campaign=%s", email, campaign.id)
        return "ignored-unknown-contact"

    recipient_id = _extract_recipient_id(payload)
    recipient = None
    if recipient_id:
        recipient = CampaignRecipient.objects.filter(id=recipient_id, campaign=campaign).first()
    if recipient is None:
        recipient = CampaignRecipient.objects.filter(campaign=campaign, contact=contact).first()

    timestamp = _extract_timestamp(payload)

    CampaignEvent.objects.create(
        campaign=campaign,
        contact=contact,
        recipient=recipient,
        event_type=internal_event,
        timestamp=timestamp,
        metadata=payload,
        dedupe_key=dedupe_key,
    )

    if recipient and internal_event in RECIPIENT_STATUS_MAP:
        new_status = RECIPIENT_STATUS_MAP[internal_event]
        # Don't downgrade e.g. "clicked" back to "delivered" if events arrive out of order.
        status_priority = [
            CampaignRecipient.Status.PENDING, CampaignRecipient.Status.SENT,
            CampaignRecipient.Status.DELIVERED, CampaignRecipient.Status.OPENED,
            CampaignRecipient.Status.CLICKED,
        ]
        terminal_negative = {
            CampaignRecipient.Status.BOUNCED, CampaignRecipient.Status.BLOCKED,
            CampaignRecipient.Status.SPAM, CampaignRecipient.Status.UNSUBSCRIBED,
        }
        if new_status in terminal_negative or new_status not in status_priority or recipient.status not in status_priority:
            recipient.status = new_status
        else:
            if status_priority.index(new_status) > status_priority.index(recipient.status):
                recipient.status = new_status
        recipient.save(update_fields=["status", "updated_at"])

    if internal_event in SUPPRESSION_REASON_MAP:
        add_suppression(email, SUPPRESSION_REASON_MAP[internal_event])

    return f"processed:{internal_event}"
