from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class ContactList(TimeStampedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contact_lists")

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "name")

    def __str__(self):
        return self.name

    @property
    def contact_count(self):
        return self.contacts.count()


class Contact(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
        BOUNCED = "bounced", "Bounced"
        BLOCKED = "blocked", "Blocked"
        SPAM = "spam", "Spam"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contacts")
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    attributes = models.JSONField(default=dict, blank=True)
    lists = models.ManyToManyField(ContactList, related_name="contacts", blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "email")
        indexes = [
            models.Index(fields=["owner", "email"]),
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.status})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email


class Suppression(TimeStampedModel):
    """
    Emails that must never receive future campaigns, regardless of the
    Contact.status on any individual owner's contact record.
    """

    class Reason(models.TextChoices):
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
        HARD_BOUNCE = "hard_bounce", "Hard bounce"
        BLOCKED = "blocked", "Blocked"
        SPAM_COMPLAINT = "spam_complaint", "Spam complaint"
        MANUAL = "manual", "Manually suppressed"

    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=30, choices=Reason.choices)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} ({self.reason})"
