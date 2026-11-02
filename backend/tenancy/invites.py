"""Send invitation / password-reset emails. Never raises: returns True only if the provider accepted it."""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_link_email(user, url, *, kind="invite"):
    """
    Email a single-use link. Uses Brevo's transactional API (no campaign quota, no OutboundMessage).
    Returns False (and logs only the error TYPE, never the link) when disabled/unconfigured/failed,
    so callers fall back to showing the link to the authorised admin once.
    """
    if not settings.SEND_INVITE_EMAILS or not settings.BREVO_API_KEY or not settings.BREVO_SENDER_EMAIL:
        return False
    from brevo.client import BrevoClient

    name = (user.first_name or "").strip() or "there"
    if kind == "reset":
        subject, lead = "Reset your password", "A password reset was requested for your account."
    else:
        subject, lead = "You have been invited", "You have been invited to join the email platform."
    html = (
        f"<p>Hi {name},</p><p>{lead} Use the button below to set your password. "
        f"The link works once and expires in 7 days.</p>"
        f'<p><a href="{url}" style="background:#2b47dd;color:#fff;padding:10px 18px;border-radius:6px;'
        f'text-decoration:none">Set your password</a></p>'
        "<p>If you did not expect this email you can ignore it.</p>"
    )
    try:
        BrevoClient().send_transactional_email(
            sender={"name": settings.BREVO_SENDER_NAME, "email": settings.BREVO_SENDER_EMAIL},
            to=[{"email": user.email, "name": name}],
            subject=subject, html_content=html, tags=[f"account-{kind}"],
        )
        return True
    except Exception as exc:  # noqa: BLE001 - provider/network failure must not break the admin action
        logger.warning("Account %s email failed for user_id=%s (%s)", kind, user.pk, type(exc).__name__)
        return False


def link_payload(user, url, *, kind="invite"):
    """Response fragment: the link is returned to the authorised admin ONLY when email could not be sent."""
    sent = send_link_email(user, url, kind=kind)
    return {"email_sent": sent, "invite_url": None if sent else url}
