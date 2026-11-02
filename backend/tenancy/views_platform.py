"""
Platform super-admin API (/api/platform/...). Only is_superuser / role=super_admin can call it.
Operations are real DB state changes; nothing here touches Postfix, DNS or the host.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from campaigns.models import Campaign, CampaignRecipient
from providers.models import OutboundMessage
from providers.registry import PROVIDERS, get_provider

from .models import AuditLog, Company, JobHeartbeat, Plan, PlatformSettings, QuotaLedger
from .permissions import IsPlatformAdmin
from .quota import usage
from .serializers import (
    AuditSerializer, CompanySerializer, PlanSerializer, PlatformSettingsSerializer,
)
from .services import audit, delivery_metrics, invite_url, paginate, scoped
from .views_company import MemberSerializer, _set_campaigns

User = get_user_model()
OM = OutboundMessage.State


class PlatformBase(APIView):
    permission_classes = [IsPlatformAdmin]


class Overview(PlatformBase):
    def get(self, request):
        p = PlatformSettings.load()
        d_used, m_used = usage(platform=True)
        since = timezone.now() - timedelta(days=1)
        r, e = scoped(since=since)
        states = {s["state"]: s["n"] for s in OutboundMessage.objects.values("state").annotate(n=Count("id"))}
        minute = OutboundMessage.objects.filter(submitting_since__gte=timezone.now() - timedelta(seconds=60)).count()
        backlog = states.get("queued", 0) + states.get("deferred", 0)
        rate = p.rate_per_minute
        return Response({
            "kpis": {
                "companies": Company.objects.count(),
                "active_companies": Company.objects.exclude(status="suspended").count(),
                "users": User.objects.filter(is_active=True).count(),
                "processed_today": QuotaLedger.objects.filter(usage_date=timezone.localdate(), state="consumed").count(),
                "active_campaigns": Campaign.objects.filter(status="processing").count(),
                "queue_backlog": backlog,
                **{k: v for k, v in delivery_metrics(r, e).items() if k in ("bounce_rate", "delivery_rate", "complaints")},
            },
            "capacity": {
                "configured_rate_per_minute": rate, "processed_this_minute": minute,
                "remaining_this_minute": None if not rate else max(rate - minute, 0),
                "queue_backlog": backlog, "deferred": states.get("deferred", 0), "failed": states.get("failed", 0),
                "needs_review": states.get("needs_review", 0), "queue_paused": p.queue_paused,
                "eta_minutes": None if not rate or not backlog else -(-backlog // rate),
                "daily_budget": p.daily_budget, "daily_used": d_used, "monthly_budget": p.monthly_budget,
                "monthly_used": m_used,
                "warning": "The rate is a software guard set by an administrator. It does not create capacity and "
                           "must follow the hosting provider's written authorisation and recipient-server limits.",
            },
        })


class Companies(PlatformBase):
    def get(self, request):
        qs = Company.objects.select_related("plan").order_by("name")
        q = request.query_params
        if q.get("search"):
            qs = qs.filter(name__icontains=q["search"])
        for f in ("status", "plan"):
            if q.get(f):
                qs = qs.filter(**{f: q[f]})
        page = paginate(request, qs)
        page["results"] = CompanySerializer(page["results"], many=True).data
        return Response(page)

    def post(self, request):
        s = CompanySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        c = s.save()
        audit(request.user, "company.created", company=c, target=c, detail={"name": c.name})
        return Response(CompanySerializer(c).data, status=201)


class CompanyDetail(PlatformBase):
    def get(self, request, pk):
        c = Company.objects.filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        r, e = scoped(company=c, since=timezone.now() - timedelta(days=30))
        return Response({**CompanySerializer(c).data, "metrics_30d": delivery_metrics(r, e),
                         "members": MemberSerializer(c.members.all(), many=True).data})

    def patch(self, request, pk):
        c = Company.objects.filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        s = CompanySerializer(c, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit(request.user, "company.updated", company=c, target=c, detail=dict(request.data))
        return Response(s.data)


class CompanyStatus(PlatformBase):
    @transaction.atomic
    def post(self, request, pk, action):
        c = Company.objects.select_for_update().filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        if action == "suspend":
            c.status = Company.Status.SUSPENDED
            c.save(update_fields=["status", "updated_at"])
            # SAFE HANDLING OF QUEUED WORK: nothing is deleted. New sends are refused at claim time,
            # and running campaigns are HELD (the sender returns early while suspended), so they
            # resume untouched on reactivation. Optionally pause them explicitly.
            held = Campaign.objects.filter(created_by__company=c, status="processing").count()
            if request.data.get("pause_running"):
                _set_campaigns(Campaign.objects.filter(created_by__company=c), "pause")
            audit(request.user, "company.suspended", company=c, target=c, detail={"held_campaigns": held})
            return Response({"status": c.status, "held_campaigns": held,
                             "detail": "New sends are refused. Running campaigns are held, not deleted."})
        if action == "reactivate":
            c.status = Company.Status.ACTIVE
            c.save(update_fields=["status", "updated_at"])
            audit(request.user, "company.reactivated", company=c, target=c)
            return Response({"status": c.status})
        return Response({"detail": "Unknown action."}, status=400)


class CompanyMembersInvite(PlatformBase):
    """Invite a company administrator (or user) into ANY company. The only supported way, besides the
    Django shell, to bootstrap a new tenant's first admin."""

    @transaction.atomic
    def post(self, request, pk):
        from .invites import link_payload

        c = Company.objects.select_for_update().filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        email = (request.data.get("email") or "").strip().lower()
        if "@" not in email:
            return Response({"detail": {"email": ["Enter a valid email address."]}}, status=400)
        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": {"email": ["A user with this email already exists."]}}, status=400)
        role = request.data.get("role", "company_admin")
        if role not in ("company_admin", "user"):
            return Response({"detail": {"role": ["Role must be 'company_admin' or 'user'."]}}, status=400)
        if c.plan_id and c.members.filter(is_active=True).count() >= c.plan.max_users:
            return Response({"detail": f"This company's plan allows {c.plan.max_users} users."}, status=400)
        u = User(username=email, email=email, first_name=str(request.data.get("first_name", ""))[:150],
                 last_name=str(request.data.get("last_name", ""))[:150], role=role, company=c)
        u.set_unusable_password()
        u.save()
        audit(request.user, "user.invited", company=c, target=u, detail={"email": email, "role": role, "by": "platform"})
        return Response({"user": MemberSerializer(u).data, **link_payload(u, invite_url(u))}, status=201)


class Users(PlatformBase):
    def get(self, request):
        qs = User.objects.select_related("company", "company__plan").order_by("email")
        q = request.query_params
        if q.get("search"):
            qs = qs.filter(email__icontains=q["search"])
        if q.get("company"):
            qs = qs.filter(company_id=q["company"])
        if q.get("active") in ("true", "false"):
            qs = qs.filter(is_active=q["active"] == "true")
        page = paginate(request, qs)
        page["results"] = [{**MemberSerializer(u).data, "company": u.company.name if u.company_id else None,
                            "plan": u.company.plan.name if u.company_id and u.company.plan_id else None}
                           for u in page["results"]]
        return Response(page)


class UserAction(PlatformBase):
    def post(self, request, pk, action):
        u = User.objects.filter(pk=pk).first()
        if not u:
            return Response({"detail": "Not found."}, status=404)
        if u.pk == request.user.pk and action == "deactivate":
            return Response({"detail": "You cannot deactivate your own account."}, status=400)
        if action in ("deactivate", "activate"):
            u.is_active = action == "activate"
            u.save(update_fields=["is_active"])
            audit(request.user, f"user.{action}d", company=u.company, target=u)
            return Response({"is_active": u.is_active})
        if action == "reset-invite":
            # A one-time, 7-day signed link. No password or token is ever stored or displayed.
            audit(request.user, "user.reset_invite", company=u.company, target=u)
            from .invites import link_payload

            return Response(link_payload(u, invite_url(u), kind="reset" if u.has_usable_password() else "invite"))
        return Response({"detail": "Unknown action."}, status=400)


class Plans(PlatformBase):
    def get(self, request):
        return Response(PlanSerializer(Plan.objects.all(), many=True).data)

    def post(self, request):
        s = PlanSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        plan = s.save()
        audit(request.user, "plan.created", company=None, target=plan)
        return Response(PlanSerializer(plan).data, status=201)


class PlanDetail(PlatformBase):
    def patch(self, request, pk):
        plan = Plan.objects.filter(pk=pk).first()
        if not plan:
            return Response({"detail": "Not found."}, status=404)
        s = PlanSerializer(plan, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit(request.user, "plan.updated", company=None, target=plan, detail=dict(request.data))
        return Response(s.data)


class PlanAction(PlatformBase):
    def post(self, request, pk, action):
        plan = Plan.objects.filter(pk=pk).first()
        if not plan:
            return Response({"detail": "Not found."}, status=404)
        if action == "archive":
            plan.is_active = False
            plan.save(update_fields=["is_active", "updated_at"])
            audit(request.user, "plan.archived", company=None, target=plan)
            return Response(PlanSerializer(plan).data)
        if action == "duplicate":
            copy = Plan.objects.get(pk=pk)
            copy.pk, copy.name, copy.is_active = None, f"{plan.name} (copy)", True
            n = 1
            while Plan.objects.filter(name=copy.name).exists():
                n += 1
                copy.name = f"{plan.name} (copy {n})"
            copy.save()
            audit(request.user, "plan.duplicated", company=None, target=copy)
            return Response(PlanSerializer(copy).data, status=201)
        return Response({"detail": "Unknown action."}, status=400)


class SettingsView(PlatformBase):
    def get(self, request):
        return Response(PlatformSettingsSerializer(PlatformSettings.load()).data)

    def patch(self, request):
        p = PlatformSettings.load()
        s = PlatformSettingsSerializer(p, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        new = s.validated_data.get("active_provider")
        if new and new != p.active_provider:
            # Validate configuration BEFORE activating (no network, no mail). A passing check means
            # "configured", not "delivers" - real delivery must be verified with controlled recipients.
            from providers.base import ProviderConfigError

            try:
                get_provider(new).validate_config()
            except ProviderConfigError as exc:
                return Response({"detail": {"active_provider": [f"Provider '{new}' is not ready: {exc}"]}}, status=400)
        s.save()
        audit(request.user, "platform.settings_changed", company=None, target=p, detail=dict(request.data))
        return Response({**s.data, "warning": "Changing the rate or provider here does not override the hosting "
                                              "provider's restrictions or add real capacity."})


class QuotaOverview(PlatformBase):
    def get(self, request):
        p = PlatformSettings.load()
        rows, allocated_daily = [], 0
        for c in Company.objects.select_related("plan").exclude(status="suspended"):
            du, mu = usage(company=c)
            allocated_daily += c.daily_limit or 0
            limit = c.daily_limit
            rows.append({"id": c.id, "name": c.name, "plan": c.plan.name if c.plan_id else None,
                         "daily_limit": limit, "daily_used": du, "monthly_limit": c.monthly_limit, "monthly_used": mu,
                         "pct_used": round(100 * du / limit, 1) if limit else None,
                         "warning": "near limit" if limit and du / limit >= 0.9 else None})
        rows.sort(key=lambda r: -r["daily_used"])
        budget = p.daily_budget
        d_used, m_used = usage(platform=True)
        return Response({
            "platform": {"daily_budget": budget, "monthly_budget": p.monthly_budget, "daily_used": d_used,
                         "monthly_used": m_used, "rate_per_minute": p.rate_per_minute},
            "allocated_daily": allocated_daily,
            "unallocated_daily": None if budget is None else budget - allocated_daily,
            "overcommitted": budget is not None and allocated_daily > budget,
            "overcommit_message": None if budget is None or allocated_daily <= budget else
            f"Company allowances total {allocated_daily:,}/day but the planned platform budget is {budget:,}/day. "
            "Not every company can use its full allowance at once; capacity is shared by fair queueing. "
            "Capacity shown is planned, not verified or guaranteed by the sending provider.",
            "companies": rows,
            "plans": PlanSerializer(Plan.objects.filter(is_active=True), many=True).data,
        })


class Queue(PlatformBase):
    def get(self, request):
        states = {s["state"]: s["n"] for s in OutboundMessage.objects.values("state").annotate(n=Count("id"))}
        oldest = OutboundMessage.objects.filter(state__in=["queued", "deferred"]).order_by("created_at").first()
        p = PlatformSettings.load()
        by_company = []
        for row in (OutboundMessage.objects.filter(state__in=["queued", "deferred", "submitting"])
                    .values("campaign__created_by__company__name").annotate(n=Count("id")).order_by("-n")[:20]):
            by_company.append({"company": row["campaign__created_by__company__name"] or "(standalone users)", "queued": row["n"]})
        return Response({
            "states": states, "paused": p.queue_paused, "rate_per_minute": p.rate_per_minute,
            "oldest_age_seconds": int((timezone.now() - oldest.created_at).total_seconds()) if oldest else 0,
            "by_company": by_company,
            "pending_recipients": CampaignRecipient.objects.filter(status="pending", campaign__status="processing").count(),
            "stuck_submitting": OutboundMessage.objects.filter(
                state="submitting", submitting_since__lt=timezone.now() - timedelta(minutes=10)).count(),
        })

    def post(self, request):
        """{"paused": true|false} -> pause/resume ALL new submissions (in-flight ones finish)."""
        p = PlatformSettings.load()
        p.queue_paused = bool(request.data.get("paused"))
        p.save(update_fields=["queue_paused", "updated_at"])
        audit(request.user, "queue.paused" if p.queue_paused else "queue.resumed", company=None, target=p)
        return Response({"paused": p.queue_paused})


class QueueMessages(PlatformBase):
    def get(self, request):
        qs = OutboundMessage.objects.select_related("campaign", "campaign__created_by", "campaign__created_by__company",
                                                    "recipient__contact").order_by("-updated_at")
        q = request.query_params
        if q.get("state"):
            qs = qs.filter(state=q["state"])
        if q.get("company"):
            qs = qs.filter(campaign__created_by__company_id=q["company"])
        if q.get("campaign"):
            qs = qs.filter(campaign_id=q["campaign"])
        if q.get("search"):
            qs = qs.filter(recipient__contact__email__icontains=q["search"])
        page = paginate(request, qs)
        page["results"] = [{
            "id": m.id, "campaign": m.campaign.name, "campaign_id": m.campaign_id,
            "company": m.campaign.created_by.company.name if m.campaign.created_by.company_id else None,
            "recipient": m.recipient.contact.email, "provider": m.provider, "state": m.state, "attempts": m.attempts,
            "provider_message_id": m.provider_message_id, "queue_id": m.provider_queue_id,
            "next_attempt_at": m.next_attempt_at, "last_error": m.last_error, "updated_at": m.updated_at,
        } for m in page["results"]]
        return Response(page)


class QueueMessageAction(PlatformBase):
    @transaction.atomic
    def post(self, request, pk, action):
        m = OutboundMessage.objects.select_for_update(of=("self",)).select_related("recipient", "campaign").filter(pk=pk).first()
        if not m:
            return Response({"detail": "Not found."}, status=404)
        rec = m.recipient
        if action == "retry":
            # Only messages the provider did NOT accept may be retried. needs_review is excluded
            # on purpose: it may already have been delivered (use "resolve" to decide explicitly).
            if m.state != OM.FAILED or (m.last_error_code or "").startswith("5"):
                return Response({"detail": "Only failed messages with a temporary (non-5xx) error can be retried."},
                                status=400)
            m.state, m.attempts, m.next_attempt_at, m.last_error = OM.QUEUED, 0, None, ""
            m.save()
            rec.status = CampaignRecipient.Status.PENDING
            rec.save(update_fields=["status", "updated_at"])
            QuotaLedger.objects.filter(recipient=rec, state="released").update(state="reserved")
            Campaign.objects.filter(pk=m.campaign_id, status__in=["failed", "sent"]).update(status="processing")
            audit(request.user, "message.retry", company=m.campaign.created_by.company, target=m)
            return Response({"state": m.state})
        if action == "resolve":
            outcome = request.data.get("outcome")
            if m.state != OM.NEEDS_REVIEW or outcome not in ("sent", "retry"):
                return Response({"detail": "Only needs_review messages; outcome must be 'sent' or 'retry'."}, status=400)
            if outcome == "sent":
                m.state = OM.ACCEPTED
                m.save()
                rec.status = CampaignRecipient.Status.SENT
                rec.sent_at = rec.sent_at or timezone.now()
                rec.save(update_fields=["status", "sent_at", "updated_at"])
            else:  # an explicit human decision that accepts the risk of a duplicate
                m.state, m.attempts, m.last_error = OM.QUEUED, 0, "Re-queued by administrator after review."
                m.save()
                rec.status = CampaignRecipient.Status.PENDING
                rec.save(update_fields=["status", "updated_at"])
                Campaign.objects.filter(pk=m.campaign_id, status__in=["failed", "sent"]).update(status="processing")
            audit(request.user, f"message.review_{outcome}", company=m.campaign.created_by.company, target=m)
            return Response({"state": m.state})
        return Response({"detail": "Unknown action."}, status=400)


class MonitorCampaigns(PlatformBase):
    def get(self, request):
        qs = Campaign.objects.select_related("created_by", "created_by__company").order_by("-created_at")
        q = request.query_params
        if q.get("status"):
            qs = qs.filter(status=q["status"])
        if q.get("company"):
            qs = qs.filter(created_by__company_id=q["company"])
        page = paginate(request, qs)
        page["results"] = [{"id": c.id, "name": c.name, "status": c.status, "provider": c.provider,
                            "company": c.created_by.company.name if c.created_by.company_id else None,
                            "owner": c.created_by.email, "recipients": c.recipients.count()} for c in page["results"]]
        return Response(page)


class CampaignAction(PlatformBase):
    def post(self, request, pk, action):
        c = Campaign.objects.select_related("created_by__company").filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        if action in ("pause", "resume"):
            n = _set_campaigns(Campaign.objects.filter(pk=pk), action)
            audit(request.user, f"campaign.{action}", company=c.created_by.company, target=c)
            return Response({"updated": n})
        if action == "switch-provider":
            new = request.data.get("provider")
            if new not in PROVIDERS:
                return Response({"detail": f"Provider must be one of {', '.join(PROVIDERS)}."}, status=400)
            if c.status not in ("processing", "paused"):
                return Response({"detail": "Only a running or paused campaign can be switched."}, status=400)
            unsafe = OutboundMessage.objects.filter(campaign=c, state__in=["submitting", "needs_review"]).count()
            if unsafe:
                return Response({"detail": f"{unsafe} message(s) have an unknown outcome. Resolve them first so "
                                           "switching provider cannot duplicate an email."}, status=409)
            try:
                get_provider(new).validate_config()
            except Exception as exc:  # noqa: BLE001
                return Response({"detail": f"Provider '{new}' is not ready: {exc}"}, status=400)
            old, c.provider = c.provider, new
            c.save(update_fields=["provider", "updated_at"])
            # Deferred (never-accepted) messages continue under the new provider; accepted ones are untouched.
            OutboundMessage.objects.filter(campaign=c, state__in=["deferred", "queued"]).update(provider=new)
            audit(request.user, "campaign.provider_switched", company=c.created_by.company, target=c,
                  detail={"from": old, "to": new})
            return Response({"provider": new})
        return Response({"detail": "Unknown action."}, status=400)


class Health(PlatformBase):
    """Real checks, clearly labelled. Provider probes connect/authenticate but NEVER send mail."""

    def get(self, request):
        out = {"checked_at": timezone.now()}
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            out["database"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            out["database"] = {"ok": False, "detail": str(exc)[:200]}
        p = PlatformSettings.load()
        providers = {}
        for name in PROVIDERS:
            if name == "smtp" and not (p.active_provider == "smtp" or request.query_params.get("probe") == "smtp"):
                from django.conf import settings as s
                providers[name] = {"ok": None, "detail": "Not the active provider (add ?probe=smtp to test).",
                                   "configured": bool(s.SMTP_HOST)}
                continue
            prov = get_provider(name)
            result = prov.health(live=True) if name == "brevo" else prov.health()
            providers[name] = {**result, "active": p.active_provider == name}
        out["providers"] = providers
        out["broker"] = _broker_status()
        now = timezone.now()
        out["jobs"] = [{"name": j.name, "last_run_at": j.last_run_at, "status": j.last_status, "detail": j.detail,
                        "age_seconds": int((now - j.last_run_at).total_seconds()),
                        "stale": (now - j.last_run_at) > timedelta(minutes=10)} for j in JobHeartbeat.objects.all()]
        day = now - timedelta(days=1)
        out["alerts"] = [a for a in (
            _alert(OutboundMessage.objects.filter(state="needs_review").count(), "messages need review (outcome unknown)"),
            _alert(OutboundMessage.objects.filter(state="failed", updated_at__gte=day).count(), "messages failed in the last 24h"),
            _alert(OutboundMessage.objects.filter(state="submitting", submitting_since__lt=now - timedelta(minutes=10)).count(),
                   "submissions stuck for over 10 minutes"),
            _alert(1 if p.queue_paused else 0, "queue is PAUSED - nothing is being submitted"),
        ) if a]
        out["label"] = "Live checks of this deployment's own dependencies. Postfix host metrics (disk/CPU/queue) come from the SMTP server's own health-check.sh."
        return Response(out)


def _alert(n, text):
    return {"count": n, "message": text} if n else None


def _broker_status():
    from django.conf import settings

    url = getattr(settings, "CELERY_BROKER_URL", "")
    if not url:
        return {"configured": False, "detail": "Celery/Redis not configured; cron-driven processing is in use."}
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=2).ping()
        return {"configured": True, "ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "ok": False, "detail": str(exc)[:200]}


class PlatformAudit(PlatformBase):
    def get(self, request):
        qs = AuditLog.objects.select_related("actor", "company")
        q = request.query_params
        if q.get("company"):
            qs = qs.filter(company_id=q["company"])
        if q.get("search"):
            qs = qs.filter(action__icontains=q["search"])
        page = paginate(request, qs)
        page["results"] = AuditSerializer(page["results"], many=True).data
        return Response(page)


class Analytics(PlatformBase):
    def get(self, request):
        try:
            days = min(max(int(request.query_params.get("days", 30)), 1), 365)
        except ValueError:
            days = 30
        since = timezone.now() - timedelta(days=days)
        rows = []
        for c in Company.objects.all():
            r, e = scoped(company=c, since=since)
            rows.append({"company": c.name, **delivery_metrics(r, e)})
        r, e = scoped(since=since)
        return Response({"days": days, "totals": delivery_metrics(r, e), "companies": rows})
