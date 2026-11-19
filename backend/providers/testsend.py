"""
Test emails through the ACTIVE provider (so "Send test" exercises the real sending path -- SMTP server,
SPF, DKIM, TLS -- not Brevo when SMTP is selected). The Brevo path is left byte-for-byte as before.

Test sends are not campaign recipient messages: they use no quota credits and create no OutboundMessage.
They are still throttled by the existing "test-email" DRF throttle scope.
"""
from brevo.services import _sample_contact_for_test
from brevo.services import send_test_email as brevo_send_test_email
from common.exceptions import ValidationAppError
from email_templates.rendering import render_template_for_contact

from .base import OutboundEmail, ProviderError
from .registry import get_provider, resolve_provider_name


def send_test_email(campaign, test_email, variant=None):
    name = resolve_provider_name(campaign)
    if name == "brevo":
        return brevo_send_test_email(campaign, test_email, variant=variant)  # unchanged behaviour (raises BrevoAPIError)

    provider = get_provider(name)
    sample = _sample_contact_for_test(campaign, test_email)
    subject_source = variant.subject if variant else campaign.subject
    html_source = variant.template.html_content if variant else campaign.template.html_content
    subject, html = render_template_for_contact(f"[TEST] {subject_source}", html_source, sample,
                                                extra_fields={"unsubscribe_url": "#"})
    tags = ["test-email", f"campaign-{campaign.id}"] + ([f"ab-variant-{variant.label}"] if variant else [])
    email = OutboundEmail(sender_name=campaign.sender_name, sender_email=campaign.sender_email, to_email=test_email,
                          to_name="", subject=subject, html=html, tags=tags, headers={"X-MailFlow-Test": "1"})
    try:
        return provider.send(email)
    except ProviderError as exc:
        # Same contract the view already uses for Brevo failures (HTTP 502 with a clear message).
        from common.exceptions import BrevoAPIError

        raise BrevoAPIError(f"{name} test send failed: {exc}") from exc
