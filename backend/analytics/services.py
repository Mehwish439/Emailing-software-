"""
Analytics computation.

Both functions here deliberately use a single aggregate() call with
conditional Count expressions instead of one .count() query per metric.
Each separate .count() is its own network round-trip to the database — on a
request/response cycle talking to a remote database (e.g. Supabase from a
Render web service), that's the difference between ~1 round trip and
~8-10 round trips for a single dashboard/analytics page load. See
docs/RENDER_DEPLOY.md's performance notes for the measured impact.
"""
from django.db.models import Count, Q

from campaigns.models import Campaign, CampaignRecipient


def _rate(numerator, denominator):
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def compute_campaign_analytics(campaign: Campaign):
    agg = CampaignRecipient.objects.filter(campaign=campaign).aggregate(
        sent=Count("id", filter=~Q(status=CampaignRecipient.Status.PENDING)),
        delivered=Count(
            "id",
            filter=Q(
                status__in=[
                    CampaignRecipient.Status.DELIVERED,
                    CampaignRecipient.Status.OPENED,
                    CampaignRecipient.Status.CLICKED,
                ]
            ),
        ),
        opened=Count("id", filter=Q(status__in=[CampaignRecipient.Status.OPENED, CampaignRecipient.Status.CLICKED])),
        clicked=Count("id", filter=Q(status=CampaignRecipient.Status.CLICKED)),
        bounced=Count("id", filter=Q(status=CampaignRecipient.Status.BOUNCED)),
        blocked=Count("id", filter=Q(status=CampaignRecipient.Status.BLOCKED)),
        spam=Count("id", filter=Q(status=CampaignRecipient.Status.SPAM)),
        unsubscribed=Count("id", filter=Q(status=CampaignRecipient.Status.UNSUBSCRIBED)),
    )

    # Soft vs hard bounce distinction comes from the event log (a different
    # table), so it's a second query — still just 2 round trips total
    # instead of the original 10.
    event_agg = campaign.events.aggregate(
        soft_bounced=Count("contact_id", filter=Q(event_type="soft_bounce"), distinct=True),
        hard_bounced=Count("contact_id", filter=Q(event_type="hard_bounce"), distinct=True),
    )

    sent = agg["sent"]
    delivered = agg["delivered"]

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "sent": sent,
        "delivered": delivered,
        "opened": agg["opened"],
        "clicked": agg["clicked"],
        "soft_bounced": event_agg["soft_bounced"],
        "hard_bounced": event_agg["hard_bounced"],
        "blocked": agg["blocked"],
        "spam": agg["spam"],
        "unsubscribed": agg["unsubscribed"],
        "delivery_rate": _rate(delivered, sent),
        "open_rate": _rate(agg["opened"], delivered),
        "click_rate": _rate(agg["clicked"], delivered),
        "bounce_rate": _rate(agg["bounced"], sent),
        "unsubscribe_rate": _rate(agg["unsubscribed"], delivered),
        "spam_rate": _rate(agg["spam"], delivered),
    }


def compute_dashboard_summary(user):
    from contacts.models import Contact
    from scheduling.models import ScheduledCampaign

    recipient_agg = CampaignRecipient.objects.filter(campaign__created_by=user).aggregate(
        emails_sent=Count("id", filter=~Q(status=CampaignRecipient.Status.PENDING)),
        delivered=Count(
            "id",
            filter=Q(
                status__in=[
                    CampaignRecipient.Status.DELIVERED,
                    CampaignRecipient.Status.OPENED,
                    CampaignRecipient.Status.CLICKED,
                ]
            ),
        ),
        opened=Count("id", filter=Q(status__in=[CampaignRecipient.Status.OPENED, CampaignRecipient.Status.CLICKED])),
        clicked=Count("id", filter=Q(status=CampaignRecipient.Status.CLICKED)),
        bounced=Count("id", filter=Q(status=CampaignRecipient.Status.BOUNCED)),
        unsubscribed=Count("id", filter=Q(status=CampaignRecipient.Status.UNSUBSCRIBED)),
        spam_complaints=Count("id", filter=Q(status=CampaignRecipient.Status.SPAM)),
    )

    # These three count different tables (Contact, Campaign, ScheduledCampaign)
    # so they can't join into the aggregate above — 3 more round trips, for
    # 4 total instead of the original 7.
    return {
        "total_contacts": Contact.objects.filter(owner=user).count(),
        "total_campaigns": Campaign.objects.filter(created_by=user).count(),
        "scheduled_campaigns": ScheduledCampaign.objects.filter(
            campaign__created_by=user, status=ScheduledCampaign.Status.SCHEDULED
        ).count(),
        **recipient_agg,
    }