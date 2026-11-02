"""
Idempotent, provider-neutral submission of ONE campaign recipient.

Guarantees (each is covered by providers/tests.py):
  * One OutboundMessage per recipient (unique idempotency key). An already-ACCEPTED
    message is never submitted again -- retries, resumed batches and duplicate cron ticks
    are all no-ops for it.
  * A claim (QUEUED/DEFERRED -> SUBMITTING) happens under a row lock, so two workers can
    never submit the same message concurrently.
  * The provider is read from campaign.provider, which is frozen when sending starts, so a
    campaign can never be split across Brevo and SMTP by accident.
  * An AMBIGUOUS result (outcome unknown) is never auto-retried: it becomes NEEDS_REVIEW.
  * An abandoned SUBMITTING claim (worker crashed mid-send) is likewise NOT re-sent after
    a stale timeout; it goes to NEEDS_REVIEW for a human decision.
"""
import logging
from datetime import timedelta
from enum import Enum

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import ratelimit
from .base import (
    ProviderAmbiguousError, ProviderConfigError, ProviderPermanentError, ProviderTemporaryError,
)
from .builder import build_campaign_email, idempotency_key_for
from .models import OutboundMessage
from .registry import get_provider
from .smtp_provider import verp_return_path

logger = logging.getLogger(__name__)

STALE_SUBMITTING = timedelta(minutes=10)
S = OutboundMessage.State


class Outcome(str, Enum):
    ACCEPTED = "accepted"
    DEFERRED = "deferred"          # temporary failure; stays PENDING, retried later
    FAILED = "failed"              # permanent / attempts exhausted; nothing was accepted
    REVIEW = "needs_review"        # outcome unknown; may have been sent; never auto-retried
    RATE_LIMITED = "rate_limited"  # capacity guard; try again next tick
    BUSY = "busy"                  # another worker holds this message
    CONFIG_ERROR = "config_error"  # provider unusable; nothing was sent


def retry_policy(provider_name):
    """(max_attempts, backoff_base_seconds). backoff 0 = retry immediately (legacy Brevo behaviour)."""
    if provider_name == "smtp":
        return max(1, settings.SMTP_MAX_RETRIES), 60
    return max(1, getattr(settings, "BREVO_MAX_SEND_ATTEMPTS", 2)), 0


def _claim(campaign, recipient, provider_name):
    """Lock-and-claim. Returns (message, early_outcome). early_outcome is not None -> do not send."""
    key = idempotency_key_for(campaign.id, recipient.id)
    now = timezone.now()
    with transaction.atomic():
        msg, _ = OutboundMessage.objects.select_for_update().get_or_create(
            idempotency_key=key,
            defaults={"campaign": campaign, "recipient": recipient, "provider": provider_name},
        )
        if msg.state in (S.ACCEPTED, S.DELIVERED, S.BOUNCED):
            return msg, Outcome.ACCEPTED
        if msg.state in (S.FAILED, S.SUPPRESSED, S.CANCELLED):
            return msg, Outcome.FAILED
        if msg.state == S.NEEDS_REVIEW:
            return msg, Outcome.REVIEW
        if msg.state == S.SUBMITTING:
            if msg.submitting_since and now - msg.submitting_since > STALE_SUBMITTING:
                msg.state = S.NEEDS_REVIEW
                msg.last_error = "A previous submission never reported a result; it may or may not have been sent."
                msg.save(update_fields=["state", "last_error", "updated_at"])
                return msg, Outcome.REVIEW
            return msg, Outcome.BUSY
        if msg.state == S.DEFERRED and msg.next_attempt_at and msg.next_attempt_at > now:
            return msg, Outcome.DEFERRED
        msg.provider = provider_name
        msg.state = S.SUBMITTING
        msg.submitting_since = now
        msg.attempts += 1
        msg.save(update_fields=["provider", "state", "submitting_since", "attempts", "updated_at"])
        return msg, None


def _finish_temporary(msg, exc, max_attempts, backoff):
    now = timezone.now()
    msg.last_error, msg.last_error_code = str(exc)[:1000], str(exc.code or "")[:20]
    msg.submitting_since = None
    if msg.attempts >= max_attempts:
        msg.state = S.FAILED
        msg.save(update_fields=["state", "last_error", "last_error_code", "submitting_since", "updated_at"])
        return Outcome.FAILED
    msg.state = S.DEFERRED
    msg.next_attempt_at = now + timedelta(seconds=backoff * (2 ** (msg.attempts - 1)))
    msg.save(update_fields=["state", "last_error", "last_error_code", "next_attempt_at", "submitting_since", "updated_at"])
    return Outcome.DEFERRED


def send_recipient(campaign, recipient) -> Outcome:
    provider_name = campaign.provider
    if not provider_name:
        raise ProviderConfigError("Campaign has no provider assigned; it must be claimed before sending.")
    max_attempts, backoff = retry_policy(provider_name)

    while True:
        if not ratelimit.may_submit(campaign):
            return Outcome.RATE_LIMITED
        msg, early = _claim(campaign, recipient, provider_name)
        if early is not None:
            return early

        try:
            provider = get_provider(provider_name)
            email = build_campaign_email(campaign, recipient)
            if provider_name == "smtp":
                email.return_path = verp_return_path(recipient.id, campaign.id)
            result = provider.send(email)
        except ProviderConfigError as exc:
            # Nothing was sent. Release the claim so it can run once the config is fixed.
            msg.state, msg.last_error, msg.submitting_since = S.QUEUED, str(exc)[:1000], None
            msg.attempts = max(0, msg.attempts - 1)
            msg.save(update_fields=["state", "last_error", "submitting_since", "attempts", "updated_at"])
            logger.error("Provider %s misconfigured: %s", provider_name, exc)
            return Outcome.CONFIG_ERROR
        except ProviderPermanentError as exc:
            msg.state, msg.last_error, msg.last_error_code = S.FAILED, str(exc)[:1000], str(exc.code or "")[:20]
            msg.submitting_since = None
            msg.save(update_fields=["state", "last_error", "last_error_code", "submitting_since", "updated_at"])
            return Outcome.FAILED
        except ProviderAmbiguousError as exc:
            msg.state, msg.last_error, msg.submitting_since = S.NEEDS_REVIEW, str(exc)[:1000], None
            msg.save(update_fields=["state", "last_error", "submitting_since", "updated_at"])
            logger.warning("Ambiguous submission for %s: %s", msg.idempotency_key, exc)
            return Outcome.REVIEW
        except ProviderTemporaryError as exc:
            outcome = _finish_temporary(msg, exc, max_attempts, backoff)
            if outcome == Outcome.DEFERRED and backoff == 0:
                continue  # legacy inline retry (provider did not accept the message)
            return outcome

        msg.state = S.ACCEPTED
        msg.provider_message_id = result.message_id
        msg.provider_queue_id = result.queue_id
        msg.accepted_at = timezone.now()
        msg.submitting_since = None
        msg.last_error = ""
        msg.save(update_fields=["state", "provider_message_id", "provider_queue_id", "accepted_at",
                                "submitting_since", "last_error", "updated_at"])
        return Outcome.ACCEPTED


def sync_state_from_event(recipient, internal_event):
    """Mirror a normalised provider event onto the OutboundMessage (never on SMTP acceptance alone)."""
    if recipient is None:
        return
    mapping = {"delivered": S.DELIVERED, "hard_bounce": S.BOUNCED, "blocked": S.FAILED}
    new = mapping.get(internal_event)
    if new:
        OutboundMessage.objects.filter(recipient=recipient).exclude(state=new).update(
            state=new, updated_at=timezone.now()
        )
