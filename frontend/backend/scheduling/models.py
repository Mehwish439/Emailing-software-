from django.db import models

from campaigns.models import Campaign
from common.models import TimeStampedModel


class ScheduledCampaign(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    campaign = models.OneToOneField(Campaign, on_delete=models.CASCADE, related_name="schedule")
    # scheduled_at is always stored normalized to UTC (USE_TZ=True); the
    # timezone the user picked is preserved separately for display purposes.
    scheduled_at = models.DateTimeField()
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["scheduled_at"]
        indexes = [models.Index(fields=["status", "scheduled_at"])]

    def __str__(self):
        return f"{self.campaign.name} @ {self.scheduled_at.isoformat()} ({self.status})"