# NEW FILE (A/B testing feature)
"""
A/B Testing business logic. Mirrors the layering the rest of the app
already uses (see campaigns/services.py's module docstring): views call
these functions, these functions call into campaigns/analytics/
email_templates as needed, and nothing here talks to Brevo directly --
brevo/services.py's send_to_recipient() is what actually sends, and it's
made variant-aware there (not duplicated here) so there's still exactly
one place campaign-sending logic lives.
"""
import random

from common.exceptions import ValidationAppError

from .models import CampaignVariant


def validate_ab_campaign_variants(campaign):
    """
    Raises ValidationAppError if `campaign` (already known to be
    campaign_type == AB_TEST) isn't actually ready to send: both Version A
    and Version B must exist, each needs a subject and a template, and
    their split_percentage values must add up to exactly 100.

    Called from campaigns.services.validate_campaign_sendable -- the
    existing single validation entry point every send path (Send Now,
    scheduled send, resumed/stuck-campaign batches) already runs through,
    so this doesn't need its own separate call site anywhere.
    """
    variants = {v.label: v for v in campaign.ab_variants.all()}

    if CampaignVariant.Label.A not in variants or CampaignVariant.Label.B not in variants:
        raise ValidationAppError(
            "An A/B test campaign requires both Version A and Version B to be configured before it can be sent."
        )

    for label, variant in variants.items():
        if not variant.subject or not variant.template_id:
            raise ValidationAppError(f"Version {label} must have a subject line and a template.")

    total_split = variants[CampaignVariant.Label.A].split_percentage + variants[CampaignVariant.Label.B].split_percentage
    if total_split != 100:
        raise ValidationAppError(
            f"Version A and Version B's audience split must add up to 100% (currently {total_split}%)."
        )


def set_campaign_variants(campaign, variants_payload):
    """
    Creates or replaces both of a campaign's A/B variants in one call.

    `variants_payload` is a list of exactly two dicts, each already
    validated shape-wise by ab_testing.serializers.VariantInputSerializer:
        [{"label": "A", "subject": "...", "template": <EmailTemplate id>,
          "split_percentage": 50}, {"label": "B", ...}]

    Raises ValidationAppError for anything invalid (wrong campaign type,
    non-draft campaign, missing/duplicate labels, split not summing to
    100, or a template that doesn't belong to this campaign's owner).
    Reuses email_templates.EmailTemplate -- no separate A/B template store.
    """
    from campaigns.models import Campaign
    from email_templates.models import EmailTemplate

    if campaign.campaign_type != Campaign.CampaignType.AB_TEST:
        raise ValidationAppError("Variants can only be set on an A/B Test campaign.")
    if campaign.status != Campaign.Status.DRAFT:
        raise ValidationAppError("Only a draft campaign's variants can be edited.")
    if len(variants_payload) != 2:
        raise ValidationAppError("Exactly two variants (Version A and Version B) are required.")

    labels = {v["label"] for v in variants_payload}
    if labels != {CampaignVariant.Label.A, CampaignVariant.Label.B}:
        raise ValidationAppError("Variants must be labeled 'A' and 'B' -- exactly one of each.")

    total_split = sum(v["split_percentage"] for v in variants_payload)
    if total_split != 100:
        raise ValidationAppError(f"The audience split between Version A and Version B must add up to 100% (got {total_split}%).")

    saved = []
    for data in variants_payload:
        if not data["subject"].strip():
            raise ValidationAppError(f"Version {data['label']} requires a subject line.")
        try:
            template = EmailTemplate.objects.get(id=data["template"], created_by=campaign.created_by)
        except EmailTemplate.DoesNotExist as exc:
            raise ValidationAppError(f"Template {data['template']} was not found for Version {data['label']}.") from exc

        variant, _ = CampaignVariant.objects.update_or_create(
            campaign=campaign,
            label=data["label"],
            defaults={
                "subject": data["subject"],
                "template": template,
                "split_percentage": data["split_percentage"],
            },
        )
        saved.append(variant)

    # Keep the campaign's own subject/template mirroring Version A. This is
    # what lets every existing subject/template-dependent code path that
    # isn't A/B-aware (dashboard campaign list, "duplicate", the
    # single-version test-send default, PDF reports) keep working exactly
    # as-is for an A/B campaign too, without needing its own A/B branch --
    # see campaigns/serializers.py and campaigns/views.py.
    variant_a = next(v for v in saved if v.label == CampaignVariant.Label.A)
    campaign.subject = variant_a.subject
    campaign.template = variant_a.template
    campaign.save(update_fields=["subject", "template", "updated_at"])

    return sorted(saved, key=lambda v: v.label)


def assign_unassigned_recipients(campaign):
    """
    Assigns every one of this campaign's CampaignRecipient rows that don't
    yet have a variant (variant_id IS NULL) to Version A or Version B,
    honoring Version A's split_percentage. Each contact ends up on exactly
    one variant -- guaranteed by the same mechanism that already prevents
    a contact being double-counted in this campaign at all:
    CampaignRecipient's unique_together = ("campaign", "contact"). A
    contact simply can't have two CampaignRecipient rows for one campaign
    to begin with, so it can't have two variants either.

    Called from campaigns.services.build_recipient_snapshot right after it
    creates any new recipient rows -- see that function's docstring. Since
    it only ever touches rows with variant IS NULL, calling this again
    later (e.g. build_recipient_snapshot is idempotent and may run more
    than once for the same campaign) never reassigns anyone already split.

    No-ops (returns without doing anything) if the campaign doesn't yet
    have both variants configured -- validate_ab_campaign_variants() is
    what actually blocks sending in that case; this function just quietly
    does nothing until the campaign is ready, so building the recipient
    snapshot never itself raises for an in-progress draft.
    """
    from campaigns.models import CampaignRecipient

    variants = {v.label: v for v in campaign.ab_variants.all()}
    if CampaignVariant.Label.A not in variants or CampaignVariant.Label.B not in variants:
        return
    variant_a = variants[CampaignVariant.Label.A]
    variant_b = variants[CampaignVariant.Label.B]

    unassigned_ids = list(
        campaign.recipients.filter(variant__isnull=True).order_by("id").values_list("id", flat=True)
    )
    if not unassigned_ids:
        return

    # Seeded on the campaign id (not the system clock) so that if this ever
    # runs twice for the same still-partially-assigned campaign, the split
    # point for a given batch size is stable rather than shuffling
    # differently each call -- not load-bearing for correctness (each
    # contact is only ever assigned once, see the docstring above), just
    # keeps behavior predictable/testable.
    rng = random.Random(f"ab-split-campaign-{campaign.id}")
    rng.shuffle(unassigned_ids)

    split_index = round(len(unassigned_ids) * variant_a.split_percentage / 100)
    a_ids = unassigned_ids[:split_index]
    b_ids = unassigned_ids[split_index:]

    if a_ids:
        CampaignRecipient.objects.filter(id__in=a_ids).update(variant=variant_a)
    if b_ids:
        CampaignRecipient.objects.filter(id__in=b_ids).update(variant=variant_b)


def compute_ab_test_results(campaign):
    """
    Per-variant Sent/Delivered/Opened/Clicked/Bounced/Unsubscribed stats
    (plus the derived rates) for an A/B campaign -- one dict per variant,
    each shaped exactly like analytics.services.compute_campaign_analytics's
    normal per-campaign output (so the frontend can reuse the same
    stat-card rendering for both), with "variant"/"variant_subject"/
    "split_percentage" added.

    Entirely computed from the real, already-stored CampaignRecipient /
    CampaignEvent rows -- see analytics/services.py -- filtered to each
    variant. Nothing here is hard-coded or estimated: reuses
    compute_campaign_analytics itself (extended with an optional
    `recipients_queryset` override -- see analytics/services.py) rather
    than reimplementing the same aggregation twice.
    """
    from analytics.services import compute_campaign_analytics
    from campaigns.models import CampaignRecipient

    results = []
    for variant in campaign.ab_variants.all().order_by("label"):
        recipients_queryset = CampaignRecipient.objects.filter(campaign=campaign, variant=variant)
        stats = compute_campaign_analytics(campaign, recipients_queryset=recipients_queryset)
        stats["variant"] = variant.label
        stats["variant_subject"] = variant.subject
        stats["split_percentage"] = variant.split_percentage
        results.append(stats)
    return results
