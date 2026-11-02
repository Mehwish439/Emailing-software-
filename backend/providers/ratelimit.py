"""
Platform-wide submission rate limit with fair sharing between companies.

Software guard only: it never raises real capacity. Configure PlatformSettings.rate_per_minute
from the hosting provider's written policy. NULL = unlimited (legacy behaviour).

Fairness: with N companies currently having pending recipients, each is entitled to
rate/N submissions per rolling minute. A company may BORROW capacity that other active
companies are not using: the capacity available to company C is
        rate - sum over OTHER active companies of max(0, share - their_recent_use)
(i.e. everything except the unused part of the others' shares), and never more than the
platform total. A company that is idle (no pending recipients) reserves nothing.
"""
import math
from datetime import timedelta

from django.utils import timezone

from campaigns.models import Campaign, CampaignRecipient
from tenancy.models import PlatformSettings

from .models import OutboundMessage


def _recent(since):
    return OutboundMessage.objects.filter(accepted_at__gte=since) | OutboundMessage.objects.filter(
        submitting_since__gte=since
    )


def active_company_keys():
    """Company ids (or negative user ids for standalone users) with pending work right now."""
    rows = (
        CampaignRecipient.objects.filter(
            status=CampaignRecipient.Status.PENDING, campaign__status=Campaign.Status.PROCESSING
        )
        .values_list("campaign__created_by__company_id", "campaign__created_by_id")
        .distinct()
    )
    return {cid if cid is not None else -uid for cid, uid in rows}


def _key_of(msg_owner_company_id, owner_id):
    return msg_owner_company_id if msg_owner_company_id is not None else -owner_id


def may_submit(campaign) -> bool:
    """True if one more message from `campaign`'s tenant may be submitted right now."""
    platform = PlatformSettings.load()
    if platform.queue_paused:
        return False
    rate = platform.rate_per_minute
    if not rate and campaign.provider == "smtp":
        from django.conf import settings as dj_settings
        rate = dj_settings.SMTP_RATE_LIMIT or None
    if not rate:
        return True
    since = timezone.now() - timedelta(seconds=60)
    recent = OutboundMessage.objects.filter(
        submitting_since__gte=since
    ).values_list("campaign__created_by__company_id", "campaign__created_by_id")
    total = 0
    used = {}
    for cid, uid in recent:
        k = _key_of(cid, uid)
        used[k] = used.get(k, 0) + 1
        total += 1
    if total >= rate:
        return False
    me = _key_of(campaign.created_by.company_id, campaign.created_by_id)
    active = active_company_keys() | {me}
    share = max(1, math.floor(rate / len(active)))
    others_unused = sum(max(0, share - used.get(k, 0)) for k in active if k != me)
    return used.get(me, 0) < rate - others_unused
