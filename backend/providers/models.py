from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class OutboundMessage(TimeStampedModel):
    """
    One row per (campaign, recipient) send attempt-chain. `idempotency_key` is unique,
    so no code path -- retry, resume, duplicate cron tick -- can create a second message
    for the same recipient, and an ACCEPTED message is never submitted again.

    States are deliberately distinct from final delivery. ACCEPTED means the provider's
    server took responsibility for the message; it does NOT mean it reached an inbox.
    DELIVERED is only set from reliable downstream evidence (a provider delivery event).
    """

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        SUBMITTING = "submitting", "Submitting"
        ACCEPTED = "accepted", "Accepted by provider"
        DEFERRED = "deferred", "Deferred (will retry)"
        DELIVERED = "delivered", "Delivered (confirmed)"
        BOUNCED = "bounced", "Bounced"
        FAILED = "failed", "Failed"
        SUPPRESSED = "suppressed", "Suppressed"
        CANCELLED = "cancelled", "Cancelled"
        NEEDS_REVIEW = "needs_review", "Needs review (outcome unknown)"

    idempotency_key = models.CharField(max_length=120, unique=True)
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="outbound_messages")
    recipient = models.OneToOneField(
        "campaigns.CampaignRecipient", on_delete=models.CASCADE, related_name="outbound_message"
    )
    provider = models.CharField(max_length=30)
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    provider_queue_id = models.CharField(max_length=60, blank=True)
    state = models.CharField(max_length=14, choices=State.choices, default=State.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    submitting_since = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    last_error_code = models.CharField(max_length=20, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["state", "next_attempt_at"]),
            models.Index(fields=["provider", "accepted_at"]),
            models.Index(fields=["campaign", "state"]),
        ]

    def __str__(self):
        return f"{self.idempotency_key} [{self.provider}:{self.state}]"


class ProviderCredential(TimeStampedModel):
    """
    Credentials + connection status for a provider that is configured from the UI (SendPulse).
    One row per provider. Brevo and SMTP are untouched: they keep using environment variables.

    Secrets are stored ONLY as a Fernet ciphertext (providers/crypto.py). Plain columns hold nothing
    sensitive: a masked client-id hint (so an admin can recognise which account is configured), the
    default sender, and the last connection-test result. The cached OAuth access token is encrypted
    too and is bound to a fingerprint of the credentials that produced it, so changing the credentials
    can never keep using a token minted for the old ones.
    """

    provider = models.CharField(max_length=30, unique=True)
    encrypted_secrets = models.TextField(blank=True)      # {"client_id", "client_secret", "webhook_secret"}
    client_id_hint = models.CharField(max_length=40, blank=True)
    sender_name = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(blank=True)
    encrypted_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    token_fingerprint = models.CharField(max_length=32, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_detail = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return f"{self.provider} credentials"


class ProviderEventLog(models.Model):
    """
    Every inbound provider event (webhook or status poll) and what was done with it.

    Two jobs: (1) idempotency -- `dedupe_key` is unique, so a retried or replayed event is recognised
    and ignored; (2) an inspectable record, including events that could not be attributed to a
    campaign. The raw payload is kept so the provider's real field names can be checked against what
    was assumed. Rows older than PROVIDER_LOG_RETENTION_DAYS are removed by `prune_provider_logs`.
    """

    provider = models.CharField(max_length=30)
    source = models.CharField(max_length=10, default="webhook")       # webhook | poll
    event_type = models.CharField(max_length=40)                     # normalised internal event
    dedupe_key = models.CharField(max_length=255, unique=True)
    outcome = models.CharField(max_length=80, blank=True)
    recipient_email = models.CharField(max_length=255, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    campaign = models.ForeignKey(
        "campaigns.Campaign", null=True, blank=True, on_delete=models.SET_NULL, related_name="provider_events"
    )
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["provider", "received_at"])]

    def __str__(self):
        return f"{self.provider}:{self.event_type} [{self.outcome}]"
