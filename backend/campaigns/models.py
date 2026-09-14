from django.conf import settings
from django.db import models

from common.models import TimeStampedModel
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate


class Campaign(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        PROCESSING = "processing", "Processing"
        SENT = "sent", "Sent"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    sender_name = models.CharField(max_length=255)
    sender_email = models.EmailField()
    template = models.ForeignKey(EmailTemplate, on_delete=models.PROTECT, related_name="campaigns")
    contact_lists = models.ManyToManyField(ContactList, related_name="campaigns", blank=True)
    segments = models.ManyToManyField("contacts.Segment", related_name="campaigns", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campaigns")
    brevo_campaign_id = models.CharField(max_length=100, blank=True, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def recipient_count(self):
        return self.recipients.count()

    def eligible_contacts_queryset(self):
        """
        Active, non-suppressed contacts from EITHER the campaign's selected
        static lists OR its selected dynamic segments (see contacts.models.
        Segment) — a contact only needs to match one of the two audience
        sources, not both, to be included.
        """
        from django.db.models import Q

        from contacts.models import Contact as ContactModel  # local import avoids circulars
        from contacts.services_suppression import filter_out_suppressed

        list_ids = list(self.contact_lists.values_list("id", flat=True))
        segment_contact_ids = set()
        for segment in self.segments.all():
            segment_contact_ids.update(segment.matching_contacts_queryset().values_list("id", flat=True))

        if not list_ids and not segment_contact_ids:
            return ContactModel.objects.none()

        audience_filter = Q()
        if list_ids:
            audience_filter |= Q(lists__id__in=list_ids)
        if segment_contact_ids:
            audience_filter |= Q(id__in=segment_contact_ids)

        contact_ids = ContactModel.objects.filter(
            audience_filter, status=ContactModel.Status.ACTIVE
        ).distinct()
        return filter_out_suppressed(contact_ids)


class CampaignRecipient(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        OPENED = "opened", "Opened"
        CLICKED = "clicked", "Clicked"
        BOUNCED = "bounced", "Bounced"
        BLOCKED = "blocked", "Blocked"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
        SPAM = "spam", "Spam"
        FAILED = "failed", "Failed"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="recipients")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="campaign_recipients")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("campaign", "contact")
        indexes = [models.Index(fields=["campaign", "status"])]

    def __str__(self):
        return f"{self.contact.email} -> {self.campaign.name} ({self.status})"
