"""
Inbound bounce / complaint processing for the self-hosted SMTP provider.

Input: a raw RFC 5322 message received at the bounce mailbox -- either a DSN
(multipart/report; report-type=delivery-status, RFC 3464) or an ARF abuse report
(report-type=feedback-report, RFC 5965).

Output: normalised events that are fed through the SAME processor Brevo webhooks use
(brevo.webhooks.process_webhook_event), so analytics, suppression, recipient status and
the dedupe guarantee behave identically for both providers. Nothing here marks a message
"delivered": only a real downstream event can do that, and DSN "relayed" notices are
deliberately ignored.

Attribution order: signed VERP return-path  ->  X-Recipient-Id/X-Campaign-Id in the
returned original headers  ->  (no attribution: event is ignored, never guessed).
"""
import logging
import re
from email import policy
from email.parser import BytesParser

from django.utils import timezone

from .smtp_provider import parse_verp

logger = logging.getLogger(__name__)

ADDR_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
# Permanent-looking codes that mailbox providers use for temporary conditions.
SOFT_DESPITE_5XX = ("5.2.2", "5.2.1")  # mailbox full / disabled -> treat as soft


def _field(msg, name):
    value = msg.get(name)
    return str(value).strip() if value else ""


def _addr(value):
    m = ADDR_RE.search(value or "")
    return m.group(0).lower() if m else ""


def classify(action, status):
    """Map RFC 3464 Action/Status to an internal event type, or None to ignore."""
    action, status = (action or "").lower(), (status or "").strip()
    if action in ("delivered", "relayed", "expanded"):
        return None  # relay acceptance is NOT inbox delivery; never record it as delivered
    if action == "delayed" or status.startswith("4"):
        return "soft_bounce"
    if status.startswith("5"):
        if status in SOFT_DESPITE_5XX:
            return "soft_bounce"
        if status.startswith("5.7"):
            return "blocked"
        return "hard_bounce"
    return "hard_bounce" if action == "failed" else None


def _original_headers(msg):
    """Find our X-* headers in the returned original message / headers part."""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else None
            if inner is not None:
                return inner
        if ctype in ("text/rfc822-headers", "text/rfc822-header"):
            raw = part.get_payload(decode=True) or b""
            return BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    return None


def parse_report(raw: bytes, envelope_recipient: str = ""):
    """Return a list of normalised event dicts parsed from one DSN/ARF message."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    original = _original_headers(msg)
    campaign_id = recipient_id = None

    verp_source = " ".join(filter(None, [envelope_recipient, _field(msg, "X-Original-To"),
                                         _field(msg, "Delivered-To"), _field(msg, "To")]))
    for token in re.findall(r"bounce\+[^\s<>,;]+", verp_source):
        parsed = parse_verp(token)
        if parsed:
            campaign_id, recipient_id = parsed
            break
    if original is not None and recipient_id is None:
        try:
            campaign_id = int(_field(original, "X-Campaign-Id") or 0) or None
            recipient_id = int(_field(original, "X-Recipient-Id") or 0) or None
        except ValueError:
            campaign_id = recipient_id = None
    original_message_id = _field(original, "Message-ID") if original is not None else ""

    events = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            blocks = part.get_payload() if part.is_multipart() else []
            for block in blocks[1:]:  # block 0 describes the message; the rest are per-recipient
                email = _addr(_field(block, "Final-Recipient") or _field(block, "Original-Recipient"))
                event = classify(_field(block, "Action"), _field(block, "Status"))
                if event and email:
                    events.append({"event": event, "email": email, "status": _field(block, "Status"),
                                   "diagnostic": _field(block, "Diagnostic-Code")[:500]})
        elif ctype == "message/feedback-report":
            blocks = part.get_payload() if part.is_multipart() else []
            fields = blocks[0] if blocks else None
            if fields is not None:
                email = _addr(_field(fields, "Original-Rcpt-To") or _field(fields, "Removal-Recipient"))
                if email and _field(fields, "Feedback-Type").lower() in ("abuse", "fraud", "other", "virus"):
                    events.append({"event": "spam", "email": email, "status": "arf",
                                   "diagnostic": f"Feedback-Type: {_field(fields, 'Feedback-Type')}"})
    for e in events:
        e.update(campaign_id=campaign_id, recipient_id=recipient_id, original_message_id=original_message_id)
    return events


def ingest_report(raw: bytes, envelope_recipient: str = ""):
    """Parse a bounce message and feed each event through the shared event processor."""
    from brevo.webhooks import process_webhook_event

    results = []
    for e in parse_report(raw, envelope_recipient):
        if not e["campaign_id"]:
            results.append("ignored-unattributable")
            logger.info("Bounce for %s could not be attributed to a campaign; ignored.", e["email"])
            continue
        stable_id = f"smtp:{e['original_message_id'] or e['campaign_id']}:{e['recipient_id'] or e['email']}"
        payload = {
            "event": e["event"], "email": e["email"], "message-id": stable_id,
            "date": timezone.now().isoformat(),
            "headers": {"X-Campaign-Id": str(e["campaign_id"]),
                        **({"X-Recipient-Id": str(e["recipient_id"])} if e["recipient_id"] else {})},
            "tags": [f"campaign-{e['campaign_id']}"],
            "provider": "smtp", "dsn_status": e["status"], "diagnostic": e["diagnostic"],
        }
        results.append(process_webhook_event(payload))
    return results
