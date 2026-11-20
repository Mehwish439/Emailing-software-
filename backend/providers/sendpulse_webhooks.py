"""
Inbound SendPulse events: signature check, normalisation, attribution, idempotent processing.

Authenticity (documented): SendPulse signs every request with the webhook's secret key.
    X-Signature: sha256=<lowercase hex HMAC-SHA256 of the RAW request body>
The check is done over the exact bytes received, before any JSON parsing.

Payload shapes handled (both are documented; accounts migrated from the old webhooks send both):
    new   {"user_id", "scope", "event_type", "occurred_at", "data": {...}}   (+ legacy data under key "0")
    old   {"event", "timestamp", "message_id", "recipient", "sender", "subject", "smtp_server_response_code", ...}
The exact field names inside the new `data` object are not published, so every lookup tries the known
spellings; the raw payload is stored in ProviderEventLog so the real names can be confirmed after the
first live event.

Reuse, not duplication: once an event is attributed to a message, it is translated into the shape the
Brevo pipeline already understands and handed to brevo.webhooks.process_webhook_event, so analytics rows,
status priority, suppression and soft-bounce escalation behave identically for both providers. Brevo's
own code is not modified.

Attribution: SendPulse cannot carry our X-Campaign-Id headers (the SMTP API has no custom headers), so an
event is matched by the message id returned at send time. If that id does not match (the docs show
differently shaped ids in different places), the only fallback is "exactly one recently accepted SendPulse
message to this address"; with zero or several candidates the event is logged as unattributed and NO
analytics are guessed. Suppression never depends on attribution: a hard bounce, spam report or
unsubscribe suppresses the address regardless.
"""
import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from contacts.services_suppression import add_suppression

from .models import OutboundMessage, ProviderEventLog
from .sendpulse_client import PROVIDER_NAME

logger = logging.getLogger(__name__)

EVENT_SYNONYMS = {
    "delivered": "delivered", "delivery": "delivered",
    "open": "opened", "opened": "opened", "email_opened": "opened",
    "click": "clicked", "clicked": "clicked", "link_clicked": "clicked", "click_on_a_link": "clicked",
    "hard_bounce": "hard_bounce", "hard_bounces": "hard_bounce", "hardbounce": "hard_bounce",
    "soft_bounce": "soft_bounce", "soft_bounces": "soft_bounce", "softbounce": "soft_bounce",
    "not_delivered": "not_delivered",
    "spam": "spam", "spam_by_user": "spam", "marked_as_spam": "spam", "email_marked_as_spam": "spam",
    "unsubscribed": "unsubscribed", "unsubscribe": "unsubscribed",
}
# internal event -> the event name brevo.webhooks.EVENT_MAP understands
TO_PIPELINE = {"delivered": "delivered", "opened": "opened", "clicked": "click", "soft_bounce": "soft_bounce",
               "hard_bounce": "hard_bounce", "spam": "spam", "unsubscribed": "unsubscribed"}
SUPPRESS_REASON = {"hard_bounce": "hard_bounce", "spam": "spam_complaint", "unsubscribed": "unsubscribed"}
FALLBACK_WINDOW = timedelta(days=14)


# --------------------------------------------------------------------------- authenticity
def verify_signature(raw_body: bytes, header_value: str, secret: str) -> bool:
    """Constant-time check of `X-Signature` (accepts "sha256=<hex>" or bare hex). Empty secret never verifies."""
    if not secret or not header_value:
        return False
    provided = header_value.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.lower())


# --------------------------------------------------------------------------- normalisation
@dataclass
class Event:
    event: str
    email: str
    message_id: str
    timestamp: object
    link: str
    raw: dict


def _first(sources, *keys):
    for src in sources:
        for k in keys:
            v = src.get(k)
            if v not in (None, "", [], {}):
                return v
    return None


def _classify_not_delivered(sources):
    """A 'not delivered' is only treated as a hard bounce when the receiving server says the mailbox/
    address is bad (enhanced status 5.1.x). Policy or reputation refusals (e.g. 5.7.1) and temporary
    4xx codes count as soft bounces, so a valid contact is never suppressed forever over our own
    sending reputation. Repeated soft bounces still escalate through the existing threshold."""
    code = str(_first(sources, "smtp_server_response_code", "smtp_answer_code") or "")
    sub = str(_first(sources, "smtp_server_response_subcode", "smtp_answer_subcode") or "")
    if code.startswith("5") and sub.startswith("5.1."):
        return "hard_bounce"
    return "soft_bounce"


def normalize(payload: dict):
    """Return an Event, or None for event types we do not act on. Raises ValueError if no recipient."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    legacy = payload.get("0") if isinstance(payload.get("0"), dict) else {}
    sources = [data, legacy, payload]
    raw_name = str(_first([payload, legacy, data], "event_type", "event") or "").lower()
    token = raw_name.rsplit(".", 1)[-1].replace("-", "_").replace(" ", "_")
    event = EVENT_SYNONYMS.get(token)
    if event is None:
        return None
    if event == "not_delivered":
        event = _classify_not_delivered(sources)
    email = str(_first(sources, "recipient", "email", "to") or "").strip().lower()
    if not email:
        raise ValueError("missing recipient")
    return Event(
        event=event, email=email,
        message_id=str(_first(sources, "message_id", "id", "email_id", "smtp_id") or ""),
        timestamp=_first(sources, "timestamp", "occurred_at"),
        link=str(_first(sources, "link", "url", "clicked_url") or ""), raw=payload,
    )


# --------------------------------------------------------------------------- attribution
def _resolve_message(ev: Event):
    qs = OutboundMessage.objects.select_related("campaign", "recipient__contact").filter(provider=PROVIDER_NAME)
    if ev.message_id:
        m = qs.filter(provider_message_id=ev.message_id).first()
        if m:
            return m, "id"
    S = OutboundMessage.State
    cands = list(qs.filter(
        recipient__contact__email__iexact=ev.email, state__in=[S.ACCEPTED, S.DELIVERED],
        accepted_at__gte=timezone.now() - FALLBACK_WINDOW,
    )[:2])
    if len(cands) == 1:
        return cands[0], "email"
    return None, ("ambiguous" if cands else "none")


# --------------------------------------------------------------------------- ingestion
@transaction.atomic
def ingest_event(payload: dict, source: str = "webhook") -> str:
    """
    Process ONE event exactly once. The log row, the analytics event and the suppression commit together:
    if anything fails the whole thing rolls back, so SendPulse's automatic retry (1m / 5m / 30m) reprocesses
    it instead of finding a "duplicate" that was never actually handled.
    """
    from brevo.webhooks import process_webhook_event

    try:
        ev = normalize(payload)
    except ValueError:
        return "rejected:missing-recipient"
    if ev is None:
        return "ignored-unhandled-event"
    ident = ev.message_id or hashlib.sha1(f"{ev.email}|{ev.event}|{ev.timestamp}".encode()).hexdigest()[:20]
    key = f"{PROVIDER_NAME}:{ident}:{ev.event}"
    log, created = ProviderEventLog.objects.get_or_create(
        dedupe_key=key,
        defaults={"provider": PROVIDER_NAME, "source": source, "event_type": ev.event, "recipient_email": ev.email,
                  "provider_message_id": ev.message_id, "payload": payload},
    )
    if not created:
        return "duplicate-ignored"

    reason = SUPPRESS_REASON.get(ev.event)
    if reason:
        add_suppression(ev.email, reason)          # independent of attribution; idempotent

    msg, how = _resolve_message(ev)
    if msg is None:
        outcome = f"unattributed-{how}" + (";suppressed" if reason else "")
    else:
        pipeline = {
            "event": TO_PIPELINE[ev.event], "email": ev.email,
            "message-id": f"{PROVIDER_NAME}:{ident}",           # prefixed: can never collide with a Brevo id
            "headers": {"X-Campaign-Id": str(msg.campaign_id), "X-Recipient-Id": str(msg.recipient_id)},
            "link": ev.link, "provider": PROVIDER_NAME, "attributed_by": how, "sendpulse": payload,
        }
        if ev.timestamp is not None:
            pipeline["date"] = ev.timestamp
        outcome = process_webhook_event(pipeline)
        log.campaign = msg.campaign
        log.provider_message_id = msg.provider_message_id
    log.outcome = outcome[:80]
    log.save(update_fields=["outcome", "campaign", "provider_message_id"])
    return outcome


# --------------------------------------------------------------------------- status poll (fallback / backfill)
def sync_recent(limit: int = 50, max_age_days: int = 3) -> dict:
    """
    Ask SendPulse about recently accepted messages (GET /smtp/emails/{id}) and feed what it reports through
    the same idempotent pipeline as webhooks. A fallback for when webhooks are not configured or were
    missed; events already seen are recognised by their dedupe key and ignored. One API call per message,
    so `limit` bounds the work (and keeps a run inside Render's 30s request window when called over HTTP).
    """
    from .sendpulse_client import SendPulseAPIError, SendPulseClient, require_config

    client = SendPulseClient(require_config())
    S = OutboundMessage.State
    msgs = (OutboundMessage.objects.select_related("recipient__contact")
            .filter(provider=PROVIDER_NAME, state__in=[S.ACCEPTED, S.DELIVERED], provider_message_id__gt="",
                    accepted_at__gte=timezone.now() - timedelta(days=max_age_days))
            .order_by("-accepted_at")[:limit])
    stats = {"checked": 0, "events": 0, "errors": 0}
    for m in msgs:
        stats["checked"] += 1
        try:
            info = client.email_info(m.provider_message_id)
        except SendPulseAPIError as exc:
            stats["errors"] += 1
            logger.warning("SendPulse status poll failed for %s: %s", m.provider_message_id, exc)
            if exc.rate_limited:
                break
            continue
        if not isinstance(info, dict):
            continue
        base = {"message_id": m.provider_message_id, "recipient": m.recipient.contact.email}
        code = str(info.get("smtp_answer_code") or "")
        found = []
        if code.startswith("2"):
            found.append({"event": "delivered"})
        elif code[:1] in ("4", "5"):
            found.append({"event": "not_delivered", "smtp_server_response_code": code,
                          "smtp_server_response_subcode": info.get("smtp_answer_subcode") or ""})
        tracking = info.get("tracking") if isinstance(info.get("tracking"), dict) else {}
        if _positive(tracking.get("open")):
            found.append({"event": "opened"})
        if _positive(tracking.get("click")):
            found.append({"event": "clicked"})
        for ev in found:
            out = ingest_event({**base, **ev, "timestamp": int(timezone.now().timestamp())}, source="poll")
            if out.startswith("processed"):
                stats["events"] += 1
    return stats


def _positive(v) -> bool:
    try:
        return int(v) > 0
    except (TypeError, ValueError):
        return False
