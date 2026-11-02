"""
Brevo adapter. Wraps the EXISTING brevo.client.BrevoClient unchanged -- credentials,
endpoint and webhook behaviour keep coming from the existing environment variables.
"""
import requests
from django.conf import settings

from brevo.client import BrevoClient
from common.exceptions import BrevoAPIError

from .base import (
    BaseProvider, OutboundEmail, ProviderAmbiguousError, ProviderConfigError,
    ProviderPermanentError, ProviderTemporaryError, SendResult,
)


def classify_brevo_error(exc: BrevoAPIError):
    """
    Maps a BrevoAPIError to the provider error taxonomy.
      * A read-timeout means Brevo may already have accepted the message -> AMBIGUOUS
        (never auto-retried; this is what previously could double-send).
      * HTTP 4xx (except 408/429) -> permanent. 5xx/429/connection errors -> temporary.
      * An error with no HTTP status and no network cause (e.g. a mocked failure)
        keeps the legacy behaviour of being treated as temporary.
    """
    if "BREVO_API_KEY is not configured" in str(exc):
        return ProviderConfigError(str(exc))
    cause = exc.__cause__
    if isinstance(cause, (requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError)):
        return ProviderAmbiguousError(str(exc), code=None)
    status = exc.status_code
    if status is not None and 400 <= status < 500 and status not in (408, 429):
        return ProviderPermanentError(str(exc), code=status, raw=exc.payload)
    return ProviderTemporaryError(str(exc), code=status, raw=exc.payload)


class BrevoProvider(BaseProvider):
    name = "brevo"

    def validate_config(self):
        if not settings.BREVO_API_KEY:
            raise ProviderConfigError("BREVO_API_KEY is not configured.")

    def send(self, email: OutboundEmail) -> SendResult:
        self.validate_config()
        client = BrevoClient()
        try:
            payload = client.send_transactional_email(
                sender={"name": email.sender_name, "email": email.sender_email},
                to=[{"email": email.to_email, "name": email.to_name}],
                subject=email.subject,
                html_content=email.html,
                tags=email.tags or None,
                headers=email.headers or None,
            )
        except BrevoAPIError as exc:
            raise classify_brevo_error(exc) from exc
        payload = payload or {}
        return SendResult(provider=self.name, message_id=str(payload.get("messageId", "")), raw=payload)

    def health(self, live=False) -> dict:
        try:
            self.validate_config()
        except ProviderConfigError as exc:
            return {"ok": False, "detail": str(exc)}
        if not live:
            return {"ok": True, "detail": "API key present (no live call made)."}
        try:
            BrevoClient().get_account()      # read-only account lookup; no email is sent
        except BrevoAPIError as exc:
            code = f" (HTTP {exc.status_code})" if exc.status_code else ""
            return {"ok": False, "detail": f"Brevo rejected or could not be reached{code}: {str(exc)[:150]}"}
        return {"ok": True, "detail": "API key accepted by Brevo (read-only account check). This does not prove sender/domain verification or inbox delivery."}
