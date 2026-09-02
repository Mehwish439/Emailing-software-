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
