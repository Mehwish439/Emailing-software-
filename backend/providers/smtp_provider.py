"""
Self-hosted SMTP (Postfix) provider. Talks to the authenticated submission service
(port 587 STARTTLS, or 465 implicit TLS) -- never to an open relay.

Failure phases are tracked explicitly so a duplicate can never be caused by a retry:
  connect / EHLO / STARTTLS / AUTH / MAIL / RCPT  -> nothing accepted  -> temporary/permanent
  DATA (message body sent, final reply not seen)   -> UNKNOWN          -> ambiguous
"""
import hashlib
import hmac
import re
import smtplib
import socket
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from django.conf import settings

from .base import (
    BaseProvider, OutboundEmail, ProviderAmbiguousError, ProviderConfigError,
    ProviderPermanentError, ProviderTemporaryError, SendResult,
)

# CRLF line endings (required on the wire) and a 998-char header limit (RFC 5322 maximum). The default
# 78-char limit makes Python RFC-2047-encode any header it cannot fold -- including List-Unsubscribe, whose
# <https://...> value has no spaces. An encoded List-Unsubscribe is unreadable to Gmail/Yahoo one-click unsubscribe.
MIME_POLICY = policy.SMTP.clone(max_line_length=998)
QUEUE_ID_RE = re.compile(r"queued as ([A-Za-z0-9]+)", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def smtp_config():
    """Collect SMTP_* settings. Secrets stay server-side and are never serialised."""
    return {
        "host": settings.SMTP_HOST, "port": settings.SMTP_PORT,
        "username": settings.SMTP_USERNAME, "password": settings.SMTP_PASSWORD,
        "use_tls": settings.SMTP_USE_TLS, "use_ssl": settings.SMTP_USE_SSL,
        "timeout": settings.SMTP_TIMEOUT,
    }


def verp_return_path(recipient_id, campaign_id):
    """
    Variable envelope return-path so a bounce can be attributed even if the bounced
    copy of our headers is stripped: bounce+<campaign>.<recipient>.<sig>@<domain>.
    """
    domain = settings.SMTP_BOUNCE_DOMAIN
    if not domain:
        return ""
    sig = verp_signature(campaign_id, recipient_id)
    return f"bounce+{campaign_id}.{recipient_id}.{sig}@{domain}"


def verp_signature(campaign_id, recipient_id):
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"{campaign_id}.{recipient_id}".encode(), hashlib.sha256).hexdigest()[:12]


def parse_verp(address):
    """Returns (campaign_id, recipient_id) if `address` is a valid signed VERP address, else None."""
    m = re.match(r"^bounce\+(\d+)\.(\d+)\.([0-9a-f]{12})@", address or "", re.I)
    if not m:
        return None
    campaign_id, recipient_id, sig = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if not hmac.compare_digest(sig, verp_signature(campaign_id, recipient_id)):
        return None
    return campaign_id, recipient_id


class SmtpProvider(BaseProvider):
    name = "smtp"

    def validate_config(self):
        cfg = smtp_config()
        if not cfg["host"]:
            raise ProviderConfigError("SMTP_HOST is not configured.")
        if cfg["use_tls"] and cfg["use_ssl"]:
            raise ProviderConfigError(
                "SMTP_USE_TLS (STARTTLS) and SMTP_USE_SSL (implicit TLS) are mutually exclusive; enable only one."
            )
        if bool(cfg["username"]) != bool(cfg["password"]):
            raise ProviderConfigError("SMTP_USERNAME and SMTP_PASSWORD must be set together.")
        if not settings.SMTP_FROM_EMAIL and not settings.BREVO_SENDER_EMAIL:
            raise ProviderConfigError("SMTP_FROM_EMAIL is not configured.")

    # ------------------------------------------------------------------ connection
    def _connect(self):
        cfg = smtp_config()
        ctx = ssl.create_default_context()
        try:
            if cfg["use_ssl"]:
                server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=cfg["timeout"], context=ctx)
            else:
                server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg["timeout"])
            server.ehlo()
            if cfg["use_tls"] and not cfg["use_ssl"]:
                if not server.has_extn("starttls"):
                    server.close()
                    raise ProviderConfigError("Server does not offer STARTTLS but SMTP_USE_TLS is enabled.")
                server.starttls(context=ctx)
                server.ehlo()
            if cfg["username"]:
                server.login(cfg["username"], cfg["password"])
            return server
        except smtplib.SMTPAuthenticationError as exc:
            # Wrong credentials are a configuration problem, not something a retry can fix.
            raise ProviderConfigError(
                f"SMTP authentication failed ({exc.smtp_code}). Check SMTP_USERNAME/SMTP_PASSWORD."
            ) from exc
        except ProviderConfigError:
            raise
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, socket.timeout, TimeoutError,
                ConnectionError, ssl.SSLError, OSError) as exc:
            raise ProviderTemporaryError(f"Could not connect to SMTP server: {exc}") from exc
        except smtplib.SMTPException as exc:
            raise ProviderTemporaryError(f"SMTP error during connection: {exc}") from exc

    # --------------------------------------------------------------------- message
    def _mime(self, email: OutboundEmail) -> EmailMessage:
        from_email = email.sender_email or settings.SMTP_FROM_EMAIL
        msg = EmailMessage(policy=MIME_POLICY)
        msg["From"] = formataddr((email.sender_name, from_email))
        msg["To"] = formataddr((email.to_name, email.to_email)) if email.to_name else email.to_email
        msg["Subject"] = email.subject
        msg["Date"] = formatdate(localtime=False)
        domain = from_email.split("@")[-1]
        # Deterministic Message-ID derived from the idempotency key: traceable in logs and
        # identical across retries of the same logical message.
        local = hashlib.sha256((email.idempotency_key or email.to_email).encode()).hexdigest()[:24]
        msg["Message-ID"] = f"<{local}@{domain}>" if email.idempotency_key else make_msgid(domain=domain)
        if settings.SMTP_REPLY_TO:
            msg["Reply-To"] = settings.SMTP_REPLY_TO
        for k, v in (email.headers or {}).items():
            if k.lower() not in {"from", "to", "subject", "date", "message-id"}:
                msg[k] = v
        text = TAG_RE.sub("", email.html or "")
        # quoted-printable keeps every line within RFC 5322's 998-char limit. Marketing HTML is
        # routinely one very long line; as plain 7bit the server rejects it ("Line too long").
        msg.set_content(text.strip() or " ", cte="quoted-printable")
        msg.add_alternative(email.html or "", subtype="html", cte="quoted-printable")
        return msg

    # ------------------------------------------------------------------------ send
    def send(self, email: OutboundEmail) -> SendResult:
        self.validate_config()
        msg = self._mime(email)
        envelope_from = email.return_path or email.sender_email or settings.SMTP_FROM_EMAIL
        server = self._connect()
        phase = "mail"
        try:
            code, resp = server.mail(envelope_from)
            if code >= 400:
                self._raise_for(code, resp, "MAIL FROM")
            phase = "rcpt"
            code, resp = server.rcpt(email.to_email)
            if code >= 400:
                self._raise_for(code, resp, "RCPT TO")
            phase = "data"
            # policy.SMTP => CRLF line endings. smtplib only normalises line endings for str input, so
            # raw bytes with bare LF are seen by the server as one giant line ("Line too long").
            code, resp = server.data(msg.as_bytes(policy=MIME_POLICY))
            if code >= 400:
                self._raise_for(code, resp, "DATA")
            server.quit()
        except smtplib.SMTPResponseException as exc:
            self._safe_close(server)
            self._raise_for(exc.smtp_code, exc.smtp_error, phase.upper())
        except smtplib.SMTPRecipientsRefused as exc:
            self._safe_close(server)
            code = next(iter(exc.recipients.values()))[0]
            self._raise_for(code, b"recipient refused", "RCPT TO")
        except (smtplib.SMTPServerDisconnected, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, OSError) as exc:
            self._safe_close(server)
            if phase == "data":
                raise ProviderAmbiguousError(f"Connection lost after the message body was sent: {exc}") from exc
            raise ProviderTemporaryError(f"Connection lost before the message was accepted: {exc}") from exc
        text = resp.decode(errors="replace") if isinstance(resp, bytes) else str(resp)
        m = QUEUE_ID_RE.search(text)
        return SendResult(
            provider=self.name, message_id=msg["Message-ID"], queue_id=m.group(1) if m else "",
            raw={"smtp_code": code, "smtp_response": text[:300]},
        )

    @staticmethod
    def _safe_close(server):
        try:
            server.close()
        except Exception:  # noqa: BLE001 -- best-effort cleanup only
            pass

    @staticmethod
    def _raise_for(code, resp, where):
        text = resp.decode(errors="replace") if isinstance(resp, bytes) else str(resp)
        msg = f"SMTP {code} at {where}: {text[:200]}"
        if code is not None and 500 <= code < 600:
            raise ProviderPermanentError(msg, code=code)
        raise ProviderTemporaryError(msg, code=code)

    # ---------------------------------------------------------------------- health
    def health(self) -> dict:
        try:
            self.validate_config()
            server = self._connect()
            banner = server.noop()
            server.quit()
            return {"ok": True, "detail": f"Connected and authenticated ({banner[0]}).",
                    "host": settings.SMTP_HOST, "port": settings.SMTP_PORT}
        except (ProviderConfigError, ProviderTemporaryError) as exc:
            return {"ok": False, "detail": str(exc), "host": settings.SMTP_HOST, "port": settings.SMTP_PORT}
