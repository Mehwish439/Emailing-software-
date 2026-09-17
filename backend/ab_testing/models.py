# NEW FILE (A/B testing feature)
"""
A/B Testing models.

Deliberately just ONE new model here, not the three (ABTest/ABTestVariant/
ABTestContactAssignment) sketched as an example in the feature spec --
the existing architecture already has cleaner homes for the other two:

  - "ABTest" itself doesn't need to exist as a separate row: a campaign
    already models "one send with its own audience/status/lifecycle" via
    campaigns.Campaign, so an A/B test is just a Campaign with
    campaign_type=AB_TEST (see campaigns/models.py) instead of a whole
    parallel object.

  - "ABTestContactAssignment" doesn't need to exist either:
    campaigns.CampaignRecipient is already the single per-(campaign,
    contact) row (with a `unique_together = ("campaign", "contact")`
    constraint) that the rest of the app uses for tracking/webhooks/
    analytics. Giving IT a nullable `variant` FK (see the migration on
    campaigns.CampaignRecipient) both records the assignment AND reuses
    that existing uniqueness constraint to guarantee a contact can never
    end up assigned to both variants of the same campaign -- a second
    model would only duplicate that guarantee, with room for the two to
    drift out of sync.

So the only genuinely new concept is "one version (A or B) of an A/B
campaign's content and its share of the audience split" -- CampaignVariant.
"""
from django.db import models

from common.models import TimeStampedModel


class CampaignVariant(TimeStampedModel):
    """
    One version ("A" or "B") of an A/B test campaign: its own subject line
    and template (reusing the existing EmailTemplate system -- see
    email_templates/models.py -- rather than introducing a second way to
    store email content), plus that version's share of the audience split.

    A campaign in A/B mode (Campaign.campaign_type == AB_TEST) has exactly
    two of these, one per Label -- enforced by unique_together below plus
    application-level validation in ab_testing/services.py
    (validate_ab_campaign_variants / set_campaign_variants), not by a
    hard DB constraint, since a campaign is allowed to sit in DRAFT with
    zero or one variant configured while the user is still building it.
    """

    class Label(models.TextChoices):
        A = "A", "Version A"
        B = "B", "Version B"

    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="ab_variants"
    )
    label = models.CharField(max_length=1, choices=Label.choices)
    subject = models.CharField(max_length=255)
    template = models.ForeignKey(
        "email_templates.EmailTemplate", on_delete=models.PROTECT, related_name="ab_variants"
    )
    # This variant's share of the audience split, e.g. 50 for a 50/50
    # split's "A" row, 30 for a 30/70 split's "A" row. The two variants'
    # split_percentage values must add up to 100 -- validated in
    # ab_testing/services.py, not enforced at the DB level (each row is
    # saved independently via update_or_create).
    split_percentage = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ("campaign", "label")
        ordering = ["label"]

    def __str__(self):
        return f"{self.campaign.name} - {self.get_label_display()}"
