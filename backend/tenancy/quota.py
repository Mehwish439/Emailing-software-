"""
Multi-level quota enforcement: Platform -> Company -> User.

* Unit of account is ONE RECIPIENT MESSAGE. A campaign to 500 eligible recipients
  reserves 500 credits.
* Reservation is transactional: platform, company and user rows are locked in a fixed
  order (platform -> company -> user) so concurrent requests serialise and cannot
  jointly exceed a limit.
* One ledger row per recipient (OneToOne) -> a retry/resume can never be charged twice.
* Lifecycle: reserved -> consumed (provider accepted) | released (never submitted:
  suppressed late, permanently failed before submission, campaign cancelled/failed).
* NULL limits mean "unlimited at this level".
"""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from common.exceptions import ValidationAppError

from .models import Company, PlatformSettings, QuotaLedger

COUNTED = (QuotaLedger.State.RESERVED, QuotaLedger.State.CONSUMED)


class QuotaExceededError(ValidationAppError):
    def __init__(self, level, needed, remaining, period):
        self.level, self.needed, self.remaining, self.period = level, needed, remaining, period
        super().__init__(
            f"{period.capitalize()} {level} email quota exceeded: this campaign needs {needed} "
            f"message credits but only {max(remaining, 0)} remain."
        )


def _sum(qs):
    return qs.filter(state__in=COUNTED).aggregate(t=Sum("credits"))["t"] or 0


def usage(*, user=None, company=None, platform=False, day=None):
    """Return (daily_used, monthly_used) for one scope."""
    day = day or timezone.localdate()
    qs = QuotaLedger.objects.all()
    if user is not None:
        qs = qs.filter(user=user)
    elif company is not None:
        qs = qs.filter(company=company)
    elif not platform:
        raise ValueError("Specify user, company or platform=True")
    daily = _sum(qs.filter(usage_date=day))
    monthly = _sum(qs.filter(usage_date__year=day.year, usage_date__month=day.month))
    return daily, monthly


def quota_snapshot(user):
    """Everything the UI needs to render a user's quota card."""
    d_used, m_used = usage(user=user)
    snap = {
        "user": {"daily_limit": user.daily_quota, "monthly_limit": user.monthly_quota,
                 "daily_used": d_used, "monthly_used": m_used},
        "company": None,
        "platform": None,
    }
    if user.company_id:
        c = user.company
        cd, cm = usage(company=c)
        snap["company"] = {"daily_limit": c.daily_limit, "monthly_limit": c.monthly_limit,
                           "daily_used": cd, "monthly_used": cm}
    p = PlatformSettings.load()
    pd, pm = usage(platform=True)
    snap["platform"] = {"daily_limit": p.daily_budget, "monthly_limit": p.monthly_budget,
                        "daily_used": pd, "monthly_used": pm, "rate_per_minute": p.rate_per_minute}
    return snap


def _check(level, limit, used_daily, used_monthly, needed, daily_limit, monthly_limit):
    if daily_limit is not None and used_daily + needed > daily_limit:
        raise QuotaExceededError(level, needed, daily_limit - used_daily, "daily")
    if monthly_limit is not None and used_monthly + needed > monthly_limit:
        raise QuotaExceededError(level, needed, monthly_limit - used_monthly, "monthly")


@transaction.atomic
def reserve_campaign_quota(campaign):
    """
    Reserve one credit per not-yet-reserved recipient of `campaign`.
    Raises QuotaExceededError (a ValidationAppError -> HTTP 400) if ANY level would be exceeded.
    Idempotent: recipients that already hold a ledger row are not charged again.
    """
    from accounts.models import User

    platform = PlatformSettings.objects.select_for_update().get_or_create(pk=1)[0]
    # of=("self",): lock ONLY the named row. PostgreSQL rejects FOR UPDATE across the nullable side of
    # an outer join (company/plan are nullable FKs), which SQLite silently ignores.
    owner = User.objects.select_for_update().get(pk=campaign.created_by_id)
    company = None
    if owner.company_id:
        company = Company.objects.select_for_update(of=("self",)).select_related("plan").get(pk=owner.company_id)
        if not company.can_send:
            raise ValidationAppError("This company's sending is suspended. Contact your platform administrator.")

    unreserved = list(
        campaign.recipients.filter(quota_entry__isnull=True).values_list("id", flat=True)
    )
    needed = len(unreserved)
    if needed:
        day = timezone.localdate()
        ud, um = usage(user=owner, day=day)
        _check("user", None, ud, um, needed, owner.daily_quota, owner.monthly_quota)
        if company:
            cd, cm = usage(company=company, day=day)
            _check("company", None, cd, cm, needed, company.daily_limit, company.monthly_limit)
        pd, pm = usage(platform=True, day=day)
        _check("platform", None, pd, pm, needed, platform.daily_budget, platform.monthly_budget)
        QuotaLedger.objects.bulk_create(
            [QuotaLedger(user=owner, company=company, campaign=campaign, recipient_id=rid, usage_date=day)
             for rid in unreserved],
            ignore_conflicts=True,
        )
    return needed


def mark_consumed(recipient_id):
    QuotaLedger.objects.filter(recipient_id=recipient_id, state=QuotaLedger.State.RESERVED).update(
        state=QuotaLedger.State.CONSUMED, updated_at=timezone.now()
    )


def release(recipient_id):
    """Release a reservation for a message that was never submitted. Consumed credits are never refunded."""
    QuotaLedger.objects.filter(recipient_id=recipient_id, state=QuotaLedger.State.RESERVED).update(
        state=QuotaLedger.State.RELEASED, updated_at=timezone.now()
    )


def release_campaign(campaign):
    """Release every still-RESERVED credit of a cancelled/failed campaign."""
    return QuotaLedger.objects.filter(campaign=campaign, state=QuotaLedger.State.RESERVED).update(
        state=QuotaLedger.State.RELEASED, updated_at=timezone.now()
    )


def reconcile():
    """
    Self-healing job: a recipient that is SENT/DELIVERED/... must be CONSUMED; one that is
    FAILED/BLOCKED must not still hold a reservation. Returns counts of rows corrected.
    """
    from campaigns.models import CampaignRecipient as R

    sent_like = [R.Status.SENT, R.Status.DELIVERED, R.Status.OPENED, R.Status.CLICKED,
                 R.Status.BOUNCED, R.Status.SPAM, R.Status.UNSUBSCRIBED]
    fixed_consumed = QuotaLedger.objects.filter(
        state=QuotaLedger.State.RESERVED, recipient__status__in=sent_like
    ).update(state=QuotaLedger.State.CONSUMED, updated_at=timezone.now())
    fixed_released = QuotaLedger.objects.filter(
        state=QuotaLedger.State.RESERVED, recipient__status__in=[R.Status.FAILED, R.Status.BLOCKED]
    ).update(state=QuotaLedger.State.RELEASED, updated_at=timezone.now())
    return {"consumed": fixed_consumed, "released": fixed_released}
