from django.db import models

from campaigns.models import Campaign, CampaignRecipient
from common.models import TimeStampedModel
from contacts.models import Contact


class CampaignEvent(TimeStampedModel):
    class EventType(models.TextChoices):
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        OPENED = "opened", "Opened"
        CLICKED = "clicked", "Clicked"
        SOFT_BOUNCE = "soft_bounce", "Soft bounce"
        HARD_BOUNCE = "hard_bounce", "Hard bounce"
        BLOCKED = "blocked", "Blocked"
        SPAM = "spam", "Spam complaint"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
        # A GET on the unsubscribe link (someone/something opened it) —
        # distinct from UNSUBSCRIBED, which only fires once a human actually
        # confirms on the confirmation page (or a mailbox provider sends the
        # explicit RFC 8058 one-click POST). Merely viewing/scanning the
        # link must never, by itself, change a contact's subscription
        # status — see contacts/views.py's unsubscribe_via_token.
        UNSUBSCRIBE_VIEWED = "unsubscribe_viewed", "Unsubscribe link viewed"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="events")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="campaign_events")
    recipient = models.ForeignKey(
        CampaignRecipient, on_delete=models.CASCADE, related_name="events", null=True, blank=True
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    timestamp = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    # Brevo's message-id + event-type pairing is what makes webhook processing idempotent.
    dedupe_key = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["campaign", "event_type"]),
            models.Index(fields=["contact", "event_type"]),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.contact.email} - {self.campaign.name}"