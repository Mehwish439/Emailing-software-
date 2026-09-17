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

    class CampaignType(models.TextChoices):
        NORMAL = "normal", "Normal Campaign"
        AB_TEST = "ab_test", "A/B Test Campaign"

    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    sender_name = models.CharField(max_length=255)
    sender_email = models.EmailField()
    template = models.ForeignKey(EmailTemplate, on_delete=models.PROTECT, related_name="campaigns")
    contact_lists = models.ManyToManyField(ContactList, related_name="campaigns", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # For an AB_TEST campaign, `subject`/`template` above are kept mirroring
    # Version A (see ab_testing.services.set_campaign_variants) so every
    # existing subject/template-dependent code path (dashboard list,
    # "duplicate", PDF reports, the default single-version test-send) keeps
    # working unmodified. The actual per-variant content lives on
    # ab_testing.CampaignVariant (campaign.ab_variants), and each recipient's
    # assignment to a variant lives on CampaignRecipient.variant below.
    campaign_type = models.CharField(max_length=20, choices=CampaignType.choices, default=CampaignType.NORMAL)
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

    @property
    def is_ab_test(self):
        return self.campaign_type == self.CampaignType.AB_TEST

    def eligible_contacts_queryset(self):
        """Contacts from the campaign's selected lists that are not suppressed."""
        from contacts.models import Contact as ContactModel  # local import avoids circulars
        from contacts.services_suppression import filter_out_suppressed

        contact_ids = ContactModel.objects.filter(
            lists__in=self.contact_lists.all(), status=ContactModel.Status.ACTIVE
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
    # Which A/B variant this contact was assigned to, for an AB_TEST
    # campaign (null for a normal campaign, and null until
    # ab_testing.services.assign_unassigned_recipients has run). This IS
    # the audience-split assignment record -- see ab_testing/models.py's
    # module docstring for why a separate "ABTestContactAssignment" model
    # would only duplicate the guarantee this row + unique_together below
    # already provides (one row per (campaign, contact) -> at most one
    # variant per contact per campaign).
    variant = models.ForeignKey(
        "ab_testing.CampaignVariant", on_delete=models.SET_NULL, null=True, blank=True, related_name="recipients"
    )

    class Meta:
        unique_together = ("campaign", "contact")
        indexes = [models.Index(fields=["campaign", "status"])]

    def __str__(self):
        return f"{self.contact.email} -> {self.campaign.name} ({self.status})"