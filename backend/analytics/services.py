from campaigns.models import Campaign, CampaignRecipient


def _rate(numerator, denominator):
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def compute_campaign_analytics(campaign: Campaign):
    recipients = CampaignRecipient.objects.filter(campaign=campaign)

    sent = recipients.exclude(status=CampaignRecipient.Status.PENDING).count()
    delivered = recipients.filter(
        status__in=[
            CampaignRecipient.Status.DELIVERED,
            CampaignRecipient.Status.OPENED,
            CampaignRecipient.Status.CLICKED,
        ]
    ).count()
    opened = recipients.filter(status__in=[CampaignRecipient.Status.OPENED, CampaignRecipient.Status.CLICKED]).count()
    clicked = recipients.filter(status=CampaignRecipient.Status.CLICKED).count()
    bounced = recipients.filter(status=CampaignRecipient.Status.BOUNCED).count()
    blocked = recipients.filter(status=CampaignRecipient.Status.BLOCKED).count()
    spam = recipients.filter(status=CampaignRecipient.Status.SPAM).count()
    unsubscribed = recipients.filter(status=CampaignRecipient.Status.UNSUBSCRIBED).count()

    # Soft vs hard bounce distinction comes from the event log, since the
    # recipient-level status only tracks "bounced" broadly.
    events = campaign.events.all()
    soft_bounced = events.filter(event_type="soft_bounce").values("contact_id").distinct().count()
    hard_bounced = events.filter(event_type="hard_bounce").values("contact_id").distinct().count()

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "sent": sent,
        "delivered": delivered,
        "opened": opened,
        "clicked": clicked,
        "soft_bounced": soft_bounced,
        "hard_bounced": hard_bounced,
        "blocked": blocked,
        "spam": spam,
        "unsubscribed": unsubscribed,
        "delivery_rate": _rate(delivered, sent),
        "open_rate": _rate(opened, delivered),
        "click_rate": _rate(clicked, delivered),
        "bounce_rate": _rate(bounced, sent),
        "unsubscribe_rate": _rate(unsubscribed, delivered),
        "spam_rate": _rate(spam, delivered),
    }


def compute_dashboard_summary(user):
    from contacts.models import Contact
    from scheduling.models import ScheduledCampaign

    campaigns = Campaign.objects.filter(created_by=user)
    recipients = CampaignRecipient.objects.filter(campaign__created_by=user)

    return {
        "total_contacts": Contact.objects.filter(owner=user).count(),
        "total_campaigns": campaigns.count(),
        "scheduled_campaigns": ScheduledCampaign.objects.filter(
            campaign__created_by=user, status=ScheduledCampaign.Status.SCHEDULED
        ).count(),
        "emails_sent": recipients.exclude(status=CampaignRecipient.Status.PENDING).count(),
        "delivered": recipients.filter(
            status__in=[
                CampaignRecipient.Status.DELIVERED,
                CampaignRecipient.Status.OPENED,
                CampaignRecipient.Status.CLICKED,
            ]
        ).count(),
        "opened": recipients.filter(
            status__in=[CampaignRecipient.Status.OPENED, CampaignRecipient.Status.CLICKED]
        ).count(),
        "clicked": recipients.filter(status=CampaignRecipient.Status.CLICKED).count(),
        "bounced": recipients.filter(status=CampaignRecipient.Status.BOUNCED).count(),
        "unsubscribed": recipients.filter(status=CampaignRecipient.Status.UNSUBSCRIBED).count(),
        "spam_complaints": recipients.filter(status=CampaignRecipient.Status.SPAM).count(),
    }
