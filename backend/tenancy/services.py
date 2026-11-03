"""Shared helpers for the admin APIs: audit logging, metrics, invites, safe pagination."""
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db.models import Count, Q
from django.utils import timezone

from analytics.models import CampaignEvent
from campaigns.models import CampaignRecipient

from .models import AuditLog

INVITE_SALT = "mailflow-invite"
INVITE_MAX_AGE = 7 * 24 * 3600


def audit(actor, action, *, company=None, target=None, detail=None, request=None):
    AuditLog.objects.create(
        company=company if company is not None else getattr(actor, "company", None),
        actor=actor, action=action,
        target_type=type(target).__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "") or ""),
        detail=detail or {},
    )


def make_invite_token(user):
    # Bound to the account's CURRENT password hash: the moment a password is set the hash changes
    # and every earlier link becomes invalid, so a leaked/old link can never reset a password.
    return signing.dumps({"uid": user.pk, "pw": user.password[-16:]}, salt=INVITE_SALT)


def read_invite_token(token):
    """Returns (user_id, password_fingerprint). Raises signing.BadSignature if forged/expired."""
    data = signing.loads(token, salt=INVITE_SALT, max_age=INVITE_MAX_AGE)
    return data["uid"], data["pw"]


def invite_url(user):
    base = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    return f"{base}/join?token={make_invite_token(user)}"


def paginate(request, items, default=25, maximum=200):
    try:
        size = min(max(int(request.query_params.get("page_size", default)), 1), maximum)
        page = max(int(request.query_params.get("page", 1)), 1)
    except ValueError:
        size, page = default, 1
    total = items.count() if hasattr(items, "count") and callable(items.count) else len(items)
    start = (page - 1) * size
    return {"count": total, "page": page, "page_size": size, "results": list(items[start:start + size])}


def day_bounds(day=None):
    day = day or timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
    return start, start + timedelta(days=1)


def delivery_metrics(recipients, events):
    """
    Counts come ONLY from recorded rows. `sent` = messages a provider accepted (SMTP/API
    acceptance, which is NOT inbox delivery); `delivered` = real downstream delivery events.
    Rates are None (not 0) when there is no denominator, so the UI can show "n/a".
    """
    sent = recipients.filter(sent_at__isnull=False).count()
    by = {r["event_type"]: r["n"] for r in events.values("event_type").annotate(n=Count("id"))}
    bounced = by.get("hard_bounce", 0) + by.get("soft_bounce", 0)

    def rate(n):
        return round(100 * n / sent, 2) if sent else None

    return {
        "accepted": sent, "delivered": by.get("delivered", 0), "bounced": bounced,
        "hard_bounces": by.get("hard_bounce", 0), "soft_bounces": by.get("soft_bounce", 0),
        "opens": by.get("opened", 0), "clicks": by.get("clicked", 0),
        "complaints": by.get("spam", 0), "unsubscribes": by.get("unsubscribed", 0),
        "delivery_rate": rate(by.get("delivered", 0)), "bounce_rate": rate(bounced),
        "open_rate": rate(by.get("opened", 0)), "click_rate": rate(by.get("clicked", 0)),
    }


def scoped(company=None, user=None, since=None):
    """(recipients, events) querysets for a user / company / whole platform within a window."""
    r, e = CampaignRecipient.objects.all(), CampaignEvent.objects.all()
    if company is not None:
        r, e = r.filter(campaign__created_by__company=company), e.filter(campaign__created_by__company=company)
    if user is not None:
        r, e = r.filter(campaign__created_by=user), e.filter(campaign__created_by=user)
    if since is not None:
        r, e = r.filter(Q(sent_at__gte=since) | Q(sent_at__isnull=True, created_at__gte=since)), e.filter(timestamp__gte=since)
    return r, e