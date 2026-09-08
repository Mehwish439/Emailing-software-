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


def compute_campaign_link_breakdown(campaign: Campaign):
    """
    Per-URL click breakdown for a campaign, plus a corrected view of
    unsubscribe activity that does NOT conflate "the unsubscribe link was
    opened/scanned" with "someone actually unsubscribed" — those are two
    different CampaignEvent types (see analytics/models.py's EventType and
    contacts/views.py's unsubscribe_via_token).

    Click data itself comes from whatever Brevo's "click" webhook forwards
    (see brevo/webhooks.py) — Brevo's own link-tracking wraps every <a
    href> in the sent HTML and reports clicks on ITS side; we only see a
    click if/when Brevo's webhook tells us about it, and only get a
    per-URL breakdown if that payload includes the clicked URL (checked
    defensively for a couple of likely field names — see webhooks.py).
    Because that request never touches our own server, we generally can't
    reliably classify those as bot vs. human (no User-Agent/IP visibility)
    — human_clicks/automated_clicks are reported as None ("unknown") for a
    URL where none of its click events carried that information, rather
    than guessing.
    """
    from analytics.models import CampaignEvent

    click_events = campaign.events.filter(event_type=CampaignEvent.EventType.CLICKED).values(
        "contact_id", "metadata"
    )

    by_url = {}
    for event in click_events:
        url = (event["metadata"] or {}).get("clicked_url") or "(unknown URL — not included in Brevo's payload)"
        bucket = by_url.setdefault(
            url, {"url": url, "total_clicks": 0, "contact_ids": set(), "human_clicks": 0, "automated_clicks": 0, "unknown_clicks": 0}
        )
        bucket["total_clicks"] += 1
        bucket["contact_ids"].add(event["contact_id"])
        is_bot = (event["metadata"] or {}).get("is_bot")
        if is_bot is True:
            bucket["automated_clicks"] += 1
        elif is_bot is False:
            bucket["human_clicks"] += 1
        else:
            bucket["unknown_clicks"] += 1

    links = []
    for bucket in by_url.values():
        links.append(
            {
                "url": bucket["url"],
                "total_clicks": bucket["total_clicks"],
                "unique_contacts": len(bucket["contact_ids"]),
                "human_clicks": bucket["human_clicks"] if bucket["unknown_clicks"] < bucket["total_clicks"] else None,
                "automated_clicks": bucket["automated_clicks"] if bucket["unknown_clicks"] < bucket["total_clicks"] else None,
            }
        )
    links.sort(key=lambda link: -link["total_clicks"])

    # Unsubscribe: link REQUESTS (every GET, human or scanner — never a
    # side-effecting action) vs CONFIRMED unsubscribes (the actual status
    # change, only from an explicit confirm/RFC-8058 POST).
    viewed_events = list(
        campaign.events.filter(event_type=CampaignEvent.EventType.UNSUBSCRIBE_VIEWED).values("contact_id", "metadata")
    )
    unique_viewers = {e["contact_id"] for e in viewed_events}
    automated_views = sum(1 for e in viewed_events if (e["metadata"] or {}).get("is_bot") is True)
    human_views = sum(1 for e in viewed_events if (e["metadata"] or {}).get("is_bot") is False)
    confirmed_count = campaign.events.filter(event_type=CampaignEvent.EventType.UNSUBSCRIBED).count()

    return {
        "campaign_id": campaign.id,
        "links": links,
        "unsubscribe": {
            "link_requests_total": len(viewed_events),
            "link_requests_unique_contacts": len(unique_viewers),
            "estimated_human_requests": human_views,
            "estimated_automated_requests": automated_views,
            "confirmed_unsubscribes": confirmed_count,
        },
    }


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