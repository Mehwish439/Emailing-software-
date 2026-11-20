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
