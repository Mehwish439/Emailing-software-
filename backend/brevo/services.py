"""
Business-logic layer around the Brevo client. This is what campaigns/services.py
calls — it never talks to brevo/client.py directly.
"""
import logging

from django.conf import settings

from common.exceptions import BrevoAPIError
from contacts.unsubscribe import generate_unsubscribe_token

from .client import BrevoClient

logger = logging.getLogger(__name__)


def _sender_payload(campaign):
    return {"name": campaign.sender_name, "email": campaign.sender_email}


def _build_unsubscribe_url(contact_id, campaign_id=None):
    token = generate_unsubscribe_token(contact_id, campaign_id)
    return f"{settings.BACKEND_BASE_URL}/api/unsubscribe/{token}/"


def _render_html(html_content, unsubscribe_url):
    """
    Replaces the {{unsubscribe_url}} merge tag (used by the "Insert
    unsubscribe link" button in the template editor) with a real,
    per-recipient unsubscribe URL. If a template doesn't include the merge
    tag, the HTML is sent unchanged — the List-Unsubscribe header (added by
    callers below) still gives recipients a working one-click unsubscribe
    even without a visible link in the body, but including a visible link is
    strongly recommended (and required by regulations like CAN-SPAM) — see
    the "Insert unsubscribe link" button in the template editor.
    """
    return html_content.replace("{{unsubscribe_url}}", unsubscribe_url)


def send_test_email(campaign, test_email):
    """
    Sends a one-off test email for a campaign via Brevo's transactional endpoint.
    Raises BrevoAPIError on failure — never silently swallowed.

    Test sends don't unsubscribe anyone real, so {{unsubscribe_url}} is
    replaced with a harmless "#" placeholder rather than a working link, and
    no List-Unsubscribe header is set.
    """
    client = BrevoClient()
    html_content = campaign.template.html_content.replace("{{unsubscribe_url}}", "#")
    return client.send_transactional_email(
        sender=_sender_payload(campaign),
        to=[{"email": test_email}],
        subject=f"[TEST] {campaign.subject}",
        html_content=html_content,
        tags=["test-email", f"campaign-{campaign.id}"],
    )


def send_to_recipient(campaign, recipient):
    """
    Sends the campaign email to a single CampaignRecipient via Brevo's
    transactional endpoint. Returns the Brevo response payload.
    Raises BrevoAPIError on failure so the caller (campaigns.services) can retry.

    Every send includes:
      - a real {{unsubscribe_url}} substitution, so a template's visible
        "Unsubscribe" link (see the template editor's "Insert unsubscribe
        link" button) actually works per-recipient
      - List-Unsubscribe / List-Unsubscribe-Post headers (RFC 8058), so
        mailbox providers can offer one-click unsubscribe directly in their
        UI. This also meaningfully helps inbox placement — bulk mail sent
        without these headers is one of the more common reasons mailbox
        providers route messages to spam.
    """
    client = BrevoClient()
    contact = recipient.contact
    unsubscribe_url = _build_unsubscribe_url(contact.id, campaign.id)
    html_content = _render_html(campaign.template.html_content, unsubscribe_url)

    return client.send_transactional_email(
        sender=_sender_payload(campaign),
        to=[{"email": contact.email, "name": contact.full_name}],
        subject=campaign.subject,
        html_content=html_content,
        tags=[f"campaign-{campaign.id}"],
        headers={
            "X-Campaign-Id": str(campaign.id),
            "X-Recipient-Id": str(recipient.id),
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def create_and_send_campaign_via_brevo(campaign):
    """
    Alternative path: registers the campaign as a native Brevo Email Campaign
    object (useful for provider-side reporting) and triggers sendNow.
    Not used for per-recipient dispatch — see campaigns/services.py, which
    sends per-recipient via send_to_recipient() so our own CampaignRecipient
    status tracking stays authoritative. This is kept for optional provider
    parity.
    """
    client = BrevoClient()
    try:
        created = client.create_email_campaign(
            name=campaign.name,
            subject=campaign.subject,
            sender=_sender_payload(campaign),
            html_content=campaign.template.html_content,
        )
        brevo_id = created.get("id")
        if brevo_id:
            client.send_email_campaign_now(brevo_id)
        return brevo_id
    except BrevoAPIError:
        logger.exception("Failed to create/send native Brevo campaign for campaign_id=%s", campaign.id)
        raise