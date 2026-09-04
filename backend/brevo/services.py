"""
Business-logic layer around the Brevo client. This is what campaigns/services.py
calls — it never talks to brevo/client.py directly.
"""
import logging

from django.conf import settings

from common.exceptions import BrevoAPIError
from contacts.unsubscribe import generate_unsubscribe_token
from email_templates.rendering import render_template_for_contact

from .client import BrevoClient

logger = logging.getLogger(__name__)


def _sender_payload(campaign):
    return {"name": campaign.sender_name, "email": campaign.sender_email}


def _build_unsubscribe_url(contact_id, campaign_id=None):
    token = generate_unsubscribe_token(contact_id, campaign_id)
    return f"{settings.BACKEND_BASE_URL}/api/unsubscribe/{token}/"


def _sample_contact_for_test(campaign, test_email):
    """
    Test sends aren't tied to a real CampaignRecipient, but the template
    still needs *some* contact to pull {{variable}} values from. Prefer a
    real eligible contact from the campaign's own lists (so the test email
    shows real data); fall back to a placeholder with everything but email
    blank if the campaign has no contacts yet.
    """
    sample = campaign.eligible_contacts_queryset().first()
    if sample is not None:
        return sample

    from types import SimpleNamespace

    return SimpleNamespace(
        first_name="", last_name="", email=test_email, phone="", full_name=test_email, attributes={},
    )


def send_test_email(campaign, test_email):
    """
    Sends a one-off test email for a campaign via Brevo's transactional endpoint.
    Raises BrevoAPIError on failure — never silently swallowed.

    Renders {{variable}} merge tags using a sample contact (see
    _sample_contact_for_test) so the test reflects what a real recipient
    would see. Test sends don't unsubscribe anyone real, so
    {{unsubscribe_url}} is replaced with a harmless "#" placeholder rather
    than a working link, and no List-Unsubscribe header is set.
    """
    client = BrevoClient()
    sample_contact = _sample_contact_for_test(campaign, test_email)
    subject, html_content = render_template_for_contact(
        f"[TEST] {campaign.subject}",
        campaign.template.html_content,
        sample_contact,
        extra_fields={"unsubscribe_url": "#"},
    )
    return client.send_transactional_email(
        sender=_sender_payload(campaign),
        to=[{"email": test_email}],
        subject=subject,
        html_content=html_content,
        tags=["test-email", f"campaign-{campaign.id}"],
    )


def send_to_recipient(campaign, recipient):
    """
    Sends the campaign email to a single CampaignRecipient via Brevo's
    transactional endpoint. Returns the Brevo response payload.
    Raises BrevoAPIError on failure so the caller (campaigns.services) can retry.

    Every send:
      - renders {{variable}} merge tags (subject and HTML) using that
        contact's own imported data (see email_templates/rendering.py), so
        every contact gets their own values, never raw {{...}} text
      - includes a real {{unsubscribe_url}} substitution, so a template's
        visible "Unsubscribe" link (see the template editor's "Insert
        unsubscribe link" button) actually works per-recipient
      - includes List-Unsubscribe / List-Unsubscribe-Post headers (RFC 8058),
        so mailbox providers can offer one-click unsubscribe directly in
        their UI. This also meaningfully helps inbox placement — bulk mail
        sent without these headers is one of the more common reasons
        mailbox providers route messages to spam.
    """
    client = BrevoClient()
    contact = recipient.contact
    unsubscribe_url = _build_unsubscribe_url(contact.id, campaign.id)
    subject, html_content = render_template_for_contact(
        campaign.subject,
        campaign.template.html_content,
        contact,
        extra_fields={"unsubscribe_url": unsubscribe_url},
    )

    return client.send_transactional_email(
        sender=_sender_payload(campaign),
        to=[{"email": contact.email, "name": contact.full_name}],
        subject=subject,
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