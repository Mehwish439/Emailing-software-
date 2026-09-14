from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class Tag(TimeStampedModel):
    """
    A flexible label a contact can carry (e.g. "VIP", "cold-lead") without
    needing a dedicated ContactList for it — a contact can have many tags,
    and tags are meant to be combined/filtered on (see Segment below),
    unlike list membership which is more of a static grouping.
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        unique_together = ("owner", "name")

    def __str__(self):
        return self.name

    @property
    def contact_count(self):
        return self.contacts.count()


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
    phone = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    attributes = models.JSONField(default=dict, blank=True)
    lists = models.ManyToManyField(ContactList, related_name="contacts", blank=True)
    tags = models.ManyToManyField(Tag, related_name="contacts", blank=True)

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


class Segment(TimeStampedModel):
    """
    A dynamic, rule-based audience: instead of a campaign only being able to
    target static ContactList membership, a segment's members are computed
    on the fly from simple criteria (tags / lists / status) every time it's
    used — a contact automatically joins or leaves it as their own
    tags/lists/status change, with no manual list-membership upkeep needed.
    Used as an additional audience source on Campaign (see
    campaigns/models.py's Campaign.segments and eligible_contacts_queryset).
    """

    class TagMatch(models.TextChoices):
        ANY = "any", "Any selected tag"
        ALL = "all", "All selected tags"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="segments")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, related_name="segments", blank=True)
    lists = models.ManyToManyField(ContactList, related_name="segments", blank=True)
    # Blank = don't filter by status at all (matches any status).
    status = models.CharField(max_length=20, choices=Contact.Status.choices, blank=True)
    tag_match = models.CharField(max_length=10, choices=TagMatch.choices, default=TagMatch.ANY)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "name")

    def __str__(self):
        return self.name

    def matching_contacts_queryset(self):
        """
        Resolves which of this owner's contacts currently match this
        segment's criteria. Recomputed fresh every call (never a stored
        membership list), so it's always up to date with each contact's
        current tags/lists/status.
        """
        qs = Contact.objects.filter(owner=self.owner)
        if self.status:
            qs = qs.filter(status=self.status)

        list_ids = list(self.lists.values_list("id", flat=True))
        if list_ids:
            qs = qs.filter(lists__id__in=list_ids)

        tag_ids = list(self.tags.values_list("id", flat=True))
        if tag_ids:
            if self.tag_match == self.TagMatch.ALL:
                # Chained .filter() calls on an M2M each add their own JOIN,
                # which is what correctly implements "has ALL of these
                # tags" (AND) rather than "has ANY of these" (OR).
                for tag_id in tag_ids:
                    qs = qs.filter(tags__id=tag_id)
            else:
                qs = qs.filter(tags__id__in=tag_ids)

        return qs.distinct()

    @property
    def contact_count(self):
        return self.matching_contacts_queryset().count()


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