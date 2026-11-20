"""
SendPulse adapter (SMTP / transactional API). Plugs into the same provider contract as Brevo and SMTP
(providers/base.py), so campaign dispatch, idempotency, quota, scheduling, pause/resume and provider
freezing all apply unchanged.

One message per API call, on purpose. SendPulse's `to` field is a shared recipient array (everyone in it
sees everyone else), and the only personalised-batch alternative is its mailing-list Campaign API, which
would bypass this platform's per-recipient tracking, suppression re-check and quota. Per-recipient sends
through POST /smtp/emails are the only approach that keeps those guarantees.

What the SMTP API does NOT accept (per the official docs): custom headers and tags. So the
X-Campaign-Id / X-Recipient-Id headers and List-Unsubscribe headers Brevo carries are not sent; events
are attributed through the message `id` SendPulse returns instead (stored in
OutboundMessage.provider_message_id), and the per-recipient unsubscribe link stays in the email body.
"""
import base64
import logging

from .base import (
    BaseProvider, OutboundEmail, ProviderAmbiguousError, ProviderConfigError, ProviderError,
    ProviderPermanentError, ProviderTemporaryError, SendResult,
)
from .sendpulse_client import (
    PROVIDER_NAME, SendPulseAPIError, SendPulseAuthError, SendPulseClient, require_config,
)
from .textify import html_to_text

logger = logging.getLogger(__name__)


def classify_sendpulse_error(exc: SendPulseAPIError) -> ProviderError:
    """
    Map a SendPulse failure onto the provider taxonomy used by the dispatcher.

      ProviderConfigError     nothing sent; the account/credentials need attention (claim is released)
      ProviderTemporaryError  PROVEN not accepted -> safe to retry after a backoff
      ProviderPermanentError  refused for good (bad request / recipient)
      ProviderAmbiguousError  may already have been queued -> NEVER auto-retried (needs review)

    The only thing that may be retried is something that provably did not reach processing. SendPulse's
    send endpoint has no idempotency key, so guessing "probably failed" would risk a duplicate email.
    """
    if isinstance(exc, SendPulseAuthError):
        return ProviderConfigError(str(exc), code=exc.status_code, raw=exc.payload)
    status = exc.status_code
    if exc.rate_limited:
        return ProviderTemporaryError(f"SendPulse rate limit: {exc}", code=429, raw=exc.payload)
    if status is None:                                   # transport-level failure
        if exc.may_have_been_processed:
            return ProviderAmbiguousError(str(exc), code=None, raw=exc.payload)
        return ProviderTemporaryError(str(exc), code=None, raw=exc.payload)
    if status == 401:                                    # still unauthorised after a token refresh
        return ProviderConfigError(f"SendPulse rejected the access token: {exc}", code=401, raw=exc.payload)
    if status == 403:                                    # account-level: SMTP not activated, plan, IP allow-list...
        return ProviderConfigError(
            f"SendPulse refused the request (HTTP 403): {exc}. Check that the SMTP service is activated "
            "on the SendPulse account.", code=403, raw=exc.payload)
    if status == 408 or status == 503:                   # request never fully processed / service unavailable
        return ProviderTemporaryError(f"SendPulse unavailable (HTTP {status}): {exc}", code=status, raw=exc.payload)
    if 400 <= status < 500:
        return ProviderPermanentError(f"SendPulse rejected the message (HTTP {status}): {exc}", code=status, raw=exc.payload)
    return ProviderAmbiguousError(f"SendPulse error after submission (HTTP {status}): {exc}", code=status, raw=exc.payload)


def build_email_object(email: OutboundEmail, sender_name: str, sender_email: str) -> dict:
    """The `email` object of POST /smtp/emails: base64 HTML + a text alternative, subject, from, to."""
    to = {"email": email.to_email}
    if email.to_name:
        to["name"] = email.to_name
    sender = {"email": sender_email}
    if sender_name:
        sender["name"] = sender_name
    return {
        "html": base64.b64encode((email.html or "").encode("utf-8")).decode("ascii"),
        "text": html_to_text(email.html) or " ",
        "subject": email.subject,
        "from": sender,
        "to": [to],
    }


class SendPulseProvider(BaseProvider):
    name = PROVIDER_NAME

    def validate_config(self):
        require_config()          # no network, sends nothing

    def send(self, email: OutboundEmail) -> SendResult:
        cfg = require_config()
        sender_email = email.sender_email or cfg.sender_email
        if not sender_email:
            raise ProviderConfigError("No sender email: set one on the campaign or in the SendPulse settings.")
        if not (email.subject or "").strip():
            raise ProviderPermanentError("The email has an empty subject.")
        payload = build_email_object(email, email.sender_name or cfg.sender_name, sender_email)
        try:
            body = SendPulseClient(cfg).send_email(payload)
        except SendPulseAPIError as exc:
            raise classify_sendpulse_error(exc) from exc
        return self._interpret(body)

    def _interpret(self, body) -> SendResult:
        if isinstance(body, dict) and body.get("result") is True:
            message_id = str(body.get("id") or "")
            if not message_id:
                logger.warning("SendPulse accepted a message but returned no id; events cannot be matched to it by id.")
            return SendResult(provider=self.name, message_id=message_id, raw=body)
        if isinstance(body, dict) and body.get("result") is False:
            raise ProviderPermanentError(
                f"SendPulse refused the message: {body.get('message') or body.get('error_code') or 'no reason given'}",
                code=body.get("error_code"), raw=body)
        # A 2xx whose body says neither yes nor no: we cannot know what happened, so never retry.
        raise ProviderAmbiguousError("SendPulse replied with an unrecognised success response.", raw=body if isinstance(body, dict) else {})

    # ------------------------------------------------------------------ health / connection test
    def health(self, live=False) -> dict:
        try:
            cfg = require_config()
        except ProviderConfigError as exc:
            return {"ok": False, "detail": str(exc)}
        if not live:
            return {"ok": True, "source": cfg.source,
                    "detail": f"Client ID/Secret present ({cfg.source}); no live call made."}
        try:
            SendPulseClient(cfg).user_info()          # read-only; sends no email
        except SendPulseAuthError as exc:
            return {"ok": False, "source": cfg.source, "detail": str(exc)[:200]}
        except SendPulseAPIError as exc:
            code = f" (HTTP {exc.status_code})" if exc.status_code else ""
            return {"ok": False, "source": cfg.source, "detail": f"SendPulse could not be reached{code}: {str(exc)[:150]}"}
        return {"ok": True, "source": cfg.source,
                "detail": "Authenticated with SendPulse (read-only account check). This does not prove sender "
                          "verification, SMTP activation or inbox delivery."}

    def test_connection(self) -> dict:
        """
        Read-only diagnostics for the Test Connection button. Sends no email. Authentication and account
        reachability decide `ok`; the sender and plan lookups are reported as warnings/info because their
        response shapes are only partially documented.
        """
        try:
            cfg = require_config()
        except ProviderConfigError as exc:
            return {"ok": False, "detail": str(exc), "checks": [], "warnings": []}
        client = SendPulseClient(cfg)
        checks, warnings = [], []
        try:
            client._fetch_token()                      # proves the Client ID/Secret work right now
            checks.append({"name": "Authentication", "ok": True, "detail": "Client ID and Secret accepted."})
        except SendPulseAuthError as exc:
            return {"ok": False, "source": cfg.source, "detail": str(exc)[:250],
                    "checks": [{"name": "Authentication", "ok": False, "detail": str(exc)[:250]}], "warnings": []}
        except SendPulseAPIError as exc:
            return {"ok": False, "source": cfg.source, "detail": f"Could not reach SendPulse: {str(exc)[:200]}",
                    "checks": [{"name": "Authentication", "ok": False, "detail": str(exc)[:200]}], "warnings": []}
        try:
            client.user_info()
            checks.append({"name": "Account", "ok": True, "detail": "Account reachable."})
        except SendPulseAPIError as exc:
            return {"ok": False, "source": cfg.source, "detail": f"Authenticated, but the account check failed: {str(exc)[:200]}",
                    "checks": checks + [{"name": "Account", "ok": False, "detail": str(exc)[:200]}], "warnings": []}
        info = {}
        try:
            senders = client.smtp_senders()
            listed = [s.lower() for s in senders if isinstance(s, str)] if isinstance(senders, list) else None
            if listed is None:
                warnings.append("Could not read the SMTP sender list (unexpected response format).")
            elif cfg.sender_email and cfg.sender_email.lower() not in listed:
                warnings.append(f"The default sender {cfg.sender_email} is not in SendPulse's SMTP sender list. "
                                "Messages from an unverified sender can be rejected.")
            elif not listed:
                warnings.append("SendPulse lists no SMTP senders yet. Add and verify a sender before sending.")
            checks.append({"name": "SMTP senders", "ok": bool(listed), "detail": f"{len(listed or [])} sender(s) listed."})
        except SendPulseAPIError as exc:
            warnings.append(f"Could not read the SMTP sender list (HTTP {exc.status_code or 'n/a'}): {str(exc)[:150]}. "
                            "The SMTP service may not be activated on this SendPulse account.")
        try:
            smtp = (client.balance_detail() or {}).get("smtp") or {}
            if isinstance(smtp, dict) and smtp.get("tariff_name"):
                info["smtp_plan"] = str(smtp["tariff_name"])
                if smtp.get("end_date"):
                    info["smtp_plan_ends"] = str(smtp["end_date"])
        except SendPulseAPIError:
            pass
        detail = "Connected to SendPulse." + (f" SMTP plan: {info['smtp_plan']}." if info.get("smtp_plan") else "")
        return {"ok": True, "source": cfg.source, "detail": detail, "checks": checks, "warnings": warnings, "account": info}
