"""
Provider-neutral construction of the email for one campaign recipient. This is the
single place merge tags, per-recipient unsubscribe links and List-Unsubscribe headers
are produced, so Brevo and SMTP can never diverge on campaign business logic.
"""
from django.conf import settings

from contacts.unsubscribe import generate_unsubscribe_token
from email_templates.rendering import render_template_for_contact

from .base import OutboundEmail


def unsubscribe_url(contact_id, campaign_id=None):
    token = generate_unsubscribe_token(contact_id, campaign_id)
    return f"{settings.BACKEND_BASE_URL}/api/unsubscribe/{token}/"


def idempotency_key_for(campaign_id, recipient_id):
    return f"camp{campaign_id}-rcpt{recipient_id}"


def build_campaign_email(campaign, recipient) -> OutboundEmail:
    contact = recipient.contact
    variant = recipient.variant
    unsub = unsubscribe_url(contact.id, campaign.id)
    subject_source = variant.subject if variant else campaign.subject
    html_source = variant.template.html_content if variant else campaign.template.html_content
    subject, html = render_template_for_contact(
        subject_source, html_source, contact, extra_fields={"unsubscribe_url": unsub}
    )
    tags = [f"campaign-{campaign.id}"]
    headers = {
        "X-Campaign-Id": str(campaign.id),
        "X-Recipient-Id": str(recipient.id),
        "List-Unsubscribe": f"<{unsub}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    if variant:
        tags.append(f"ab-variant-{variant.label}")
        headers["X-AB-Variant"] = variant.label
    return OutboundEmail(
        sender_name=campaign.sender_name,
        sender_email=campaign.sender_email,
        to_email=contact.email,
        to_name=contact.full_name,
        subject=subject,
        html=html,
        tags=tags,
        headers=headers,
        idempotency_key=idempotency_key_for(campaign.id, recipient.id),
    )
