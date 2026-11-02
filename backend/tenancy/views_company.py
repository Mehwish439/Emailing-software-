"""
Company-admin API (/api/company/...). EVERY query is scoped server-side to request.user.company;
nothing here accepts a company id from the client, so one company can never reach another's data.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import CampaignEvent
from campaigns.models import Campaign
from contacts.models import Contact, Suppression

from .models import AuditLog, QuotaLedger
from .permissions import IsCompanyAdmin
from .quota import usage
from .serializers import AuditSerializer, CompanySerializer, MemberSerializer
from .invites import link_payload
from .services import audit, day_bounds, delivery_metrics, invite_url, paginate, scoped

User = get_user_model()


class CompanyBase(APIView):
    permission_classes = [IsCompanyAdmin]

    @property
    def company(self):
        return self.request.user.company

    def members(self):
        return User.objects.filter(company=self.company)


def _allocation(company, exclude_user_id=None, new_value=None, user_id=None):
    qs = User.objects.filter(company=company, is_active=True)
    total = 0
    for u in qs:
        if user_id is not None and u.id == user_id:
            total += new_value or 0
        else:
            total += u.daily_quota or 0
    return total


class Overview(CompanyBase):
    def get(self, request):
        c = self.company
        d_used, m_used = usage(company=c)
        start, end = day_bounds()
        recipients, events = scoped(company=c, since=timezone.now() - timedelta(days=7))
        week = delivery_metrics(recipients, events)
        sent_today = scoped(company=c)[0].filter(sent_at__gte=start, sent_at__lt=end).count()
        series = []
        for i in range(6, -1, -1):
            day = timezone.localdate() - timedelta(days=i)
            s, e = day_bounds(day)
            series.append({"date": day.isoformat(),
                           "sent": scoped(company=c)[0].filter(sent_at__gte=s, sent_at__lt=e).count()})
        from providers.models import OutboundMessage

        queue = OutboundMessage.objects.filter(campaign__created_by__company=c)
        return Response({
            "company": CompanySerializer(c).data,
            "kpis": {
                "sent_today": sent_today,
                "daily_remaining": None if c.daily_limit is None else max(c.daily_limit - d_used, 0),
                "active_members": c.members.filter(is_active=True).count(),
                "max_users": c.plan.max_users if c.plan_id else None,
                "campaigns_running": Campaign.objects.filter(created_by__company=c, status="processing").count(),
                **{k: week[k] for k in ("delivery_rate", "bounce_rate", "open_rate", "click_rate")},
            },
            "quota": {"daily_limit": c.daily_limit, "daily_used": d_used, "monthly_limit": c.monthly_limit,
                      "monthly_used": m_used,
                      "queued_messages": queue.filter(state__in=["queued", "deferred", "submitting"]).count(),
                      "note": "Limits are this company's share of shared platform capacity; actual sending "
                              "also respects the platform rate limit and fair queueing."},
            "week": week, "series": series,
        })


class Members(CompanyBase):
    def get(self, request):
        qs = self.members().order_by("first_name", "email")
        q = request.query_params.get("search")
        if q:
            qs = qs.filter(email__icontains=q) | qs.filter(first_name__icontains=q) | qs.filter(last_name__icontains=q)
        page = paginate(request, qs)
        page["results"] = MemberSerializer(page["results"], many=True).data
        return Response(page)

    @transaction.atomic
    def post(self, request):
        """Invite a user. Creates the account WITHOUT a password and returns a 7-day invite link."""
        c = self.company
        email = (request.data.get("email") or "").strip().lower()
        if "@" not in email:
            return Response({"detail": "Enter a valid email address."}, status=400)
        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "A user with this email already exists."}, status=400)
        if c.plan_id and c.members.filter(is_active=True).count() >= c.plan.max_users:
            return Response({"detail": f"Your plan allows {c.plan.max_users} users. Upgrade or deactivate a user first."},
                            status=400)
        role = request.data.get("role", "user")
        if role not in ("user", "company_admin"):
            return Response({"detail": "Role must be 'user' or 'company_admin'."}, status=400)
        daily = request.data.get("daily_quota")
        monthly = request.data.get("monthly_quota")
        err = _validate_quotas(c, None, daily, monthly)
        if err:
            return Response({"detail": err}, status=400)
        user = User(username=email, email=email, first_name=request.data.get("first_name", ""),
                    last_name=request.data.get("last_name", ""), role=role, company=c,
                    daily_quota=daily, monthly_quota=monthly)
        user.set_unusable_password()
        user.save()
        audit(request.user, "user.invited", target=user, detail={"email": email, "role": role})
        return Response({"user": MemberSerializer(user).data, **link_payload(user, invite_url(user))}, status=201)


def _validate_quotas(company, user, daily, monthly):
    for label, v in (("Daily", daily), ("Monthly", monthly)):
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            return f"{label} quota must be a non-negative whole number or null."
    if daily is not None and monthly is not None and daily > monthly:
        return "A daily quota cannot exceed the monthly quota."
    if company.daily_limit is not None and daily is not None:
        if daily > company.daily_limit:
            return f"A user's daily quota cannot exceed the company allowance ({company.daily_limit:,})."
        if not company.allow_overallocation:
            total = _allocation(company, user_id=user.id if user else None, new_value=daily)
            if user is None:
                total += daily
            if total > company.daily_limit:
                return (f"Assigned daily quotas would total {total:,}, above the company allowance of "
                        f"{company.daily_limit:,}. Lower another user's quota first.")
    return None


class MemberDetail(CompanyBase):
    def _get(self, pk):
        return self.members().filter(pk=pk).first()

    def patch(self, request, pk):
        user = self._get(pk)
        if user is None:
            return Response({"detail": "Not found."}, status=404)
        data = request.data
        changes = {}
        if "daily_quota" in data or "monthly_quota" in data:
            daily = data.get("daily_quota", user.daily_quota)
            monthly = data.get("monthly_quota", user.monthly_quota)
            err = _validate_quotas(self.company, user, daily, monthly)
            if err:
                return Response({"detail": err}, status=400)
            changes.update(daily_quota=daily, monthly_quota=monthly)
        if "role" in data:
            if data["role"] not in ("user", "company_admin"):
                return Response({"detail": "Role must be 'user' or 'company_admin'."}, status=400)
            if user.pk == request.user.pk and data["role"] != "company_admin":
                return Response({"detail": "You cannot remove your own admin role."}, status=400)
            changes["role"] = data["role"]
        if "is_active" in data:
            if user.pk == request.user.pk and not data["is_active"]:
                return Response({"detail": "You cannot deactivate your own account."}, status=400)
            if data["is_active"] and not user.is_active and self.company.plan_id and \
                    self.company.members.filter(is_active=True).count() >= self.company.plan.max_users:
                return Response({"detail": "No free seats on your plan."}, status=400)
            changes["is_active"] = bool(data["is_active"])
        for f in ("first_name", "last_name"):
            if f in data:
                changes[f] = str(data[f])[:150]
        for k, v in changes.items():
            setattr(user, k, v)
        user.save()
        audit(request.user, "user.updated", target=user, detail=changes)
        return Response(MemberSerializer(user).data)


class ResendInvite(CompanyBase):
    """Re-issue a link for a member of THIS company who has not set a password yet. Old links stay valid
    until used or expired (they are bound to the password hash, not to a counter)."""

    def post(self, request, pk):
        user = self.members().filter(pk=pk).first()
        if user is None:
            return Response({"detail": "Not found."}, status=404)
        if user.has_usable_password():
            return Response({"detail": "This user has already accepted their invitation."}, status=400)
        if not user.is_active:
            return Response({"detail": "Reactivate this user before resending the invitation."}, status=400)
        audit(request.user, "user.invite_resent", target=user, detail={"email": user.email})
        return Response({"user_id": user.id, **link_payload(user, invite_url(user))})


class MemberCampaignAction(CompanyBase):
    def post(self, request, pk, action):
        user = self.members().filter(pk=pk).first()
        if user is None:
            return Response({"detail": "Not found."}, status=404)
        n = _set_campaigns(user.campaigns.all(), action)
        audit(request.user, f"campaigns.{action}", target=user, detail={"count": n})
        return Response({"updated": n})


def _set_campaigns(qs, action):
    if action == "pause":
        return qs.filter(status=Campaign.Status.PROCESSING).update(status=Campaign.Status.PAUSED)
    if action == "resume":
        return qs.filter(status=Campaign.Status.PAUSED).update(status=Campaign.Status.PROCESSING)
    raise ValueError(action)


class Quotas(CompanyBase):
    def get(self, request):
        c = self.company
        rows = []
        for u in self.members().filter(is_active=True).order_by("email"):
            du, mu = usage(user=u)
            rows.append({"id": u.id, "email": u.email, "name": f"{u.first_name} {u.last_name}".strip() or u.email,
                         "daily_quota": u.daily_quota, "monthly_quota": u.monthly_quota,
                         "daily_used": du, "monthly_used": mu})
        assigned = sum(r["daily_quota"] or 0 for r in rows)
        limit = c.daily_limit
        d_used, m_used = usage(company=c)
        return Response({
            "daily_limit": limit, "monthly_limit": c.monthly_limit, "daily_used": d_used, "monthly_used": m_used,
            "assigned_daily": assigned,
            "unallocated_daily": None if limit is None else limit - assigned,
            "over_allocated": limit is not None and assigned > limit,
            "allow_overallocation": c.allow_overallocation,
            "rules": ["Individual limits are sub-limits inside the company allowance.",
                      "Unused user quota never increases the company allowance.",
                      "Raising a user's quota does not raise your subscription allowance.",
                      "Real sending is also bound by the shared platform rate and capacity."],
            "users": rows,
        })


class CompanyCampaigns(CompanyBase):
    def get(self, request):
        qs = Campaign.objects.filter(created_by__company=self.company).select_related("created_by").order_by("-created_at")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        if request.query_params.get("owner"):
            qs = qs.filter(created_by_id=request.query_params["owner"])
        page = paginate(request, qs)
        out = []
        for c in page["results"]:
            total = c.recipients.count()
            done = c.recipients.exclude(status="pending").count()
            r, e = scoped(company=self.company)
            r, e = r.filter(campaign=c), e.filter(campaign=c)
            out.append({"id": c.id, "name": c.name, "owner": c.created_by.email, "owner_id": c.created_by_id,
                        "status": c.status, "provider": c.provider, "recipients": total,
                        "progress": round(100 * done / total, 1) if total else None,
                        **delivery_metrics(r, e)})
        page["results"] = out
        return Response(page)


class CompanyCampaignAction(CompanyBase):
    def post(self, request, pk, action):
        c = Campaign.objects.filter(pk=pk, created_by__company=self.company).first()
        if c is None:
            return Response({"detail": "Not found."}, status=404)
        if action not in ("pause", "resume"):
            return Response({"detail": "Unknown action."}, status=400)
        n = _set_campaigns(Campaign.objects.filter(pk=c.pk), action)
        if not n:
            return Response({"detail": f"Campaign is '{c.status}' and cannot be {action}d."}, status=400)
        audit(request.user, f"campaign.{action}", target=c)
        return Response({"id": c.id, "status": Campaign.objects.get(pk=c.pk).status})


class CompanyAnalytics(CompanyBase):
    def get(self, request):
        try:
            days = min(max(int(request.query_params.get("days", 30)), 1), 365)
        except ValueError:
            days = 30
        since = timezone.now() - timedelta(days=days)
        c = self.company
        r, e = scoped(company=c, since=since)
        if request.query_params.get("user"):
            r, e = r.filter(campaign__created_by_id=request.query_params["user"]), e.filter(campaign__created_by_id=request.query_params["user"])
        by_user = []
        for u in self.members().order_by("email"):
            ur, ue = scoped(company=c, user=u, since=since)
            m = delivery_metrics(ur, ue)
            if m["accepted"] or m["opens"]:
                by_user.append({"user": u.email, **m})
        top = []
        for camp in Campaign.objects.filter(created_by__company=c, created_at__gte=since)[:100]:
            cr, ce = r.filter(campaign=camp), e.filter(campaign=camp)
            m = delivery_metrics(cr, ce)
            if m["accepted"]:
                top.append({"campaign": camp.name, "owner": camp.created_by.email, **m})
        top.sort(key=lambda x: -(x["open_rate"] or 0))
        return Response({"days": days, "totals": delivery_metrics(r, e), "by_user": by_user, "campaigns": top[:20],
                         "note": "Counts come from recorded provider events only. 'accepted' means a provider "
                                 "took the message; it is not proof of inbox delivery."})


class CompanySuppressions(CompanyBase):
    def get(self, request):
        """Suppressions are platform-global; a company only sees entries matching ITS OWN contacts."""
        emails = Contact.objects.filter(owner__company=self.company).values("email")
        qs = Suppression.objects.filter(email__in=emails).order_by("-created_at")
        if request.query_params.get("reason"):
            qs = qs.filter(reason=request.query_params["reason"])
        page = paginate(request, qs)
        page["results"] = [{"email": s.email, "reason": s.reason, "created_at": s.created_at} for s in page["results"]]
        return Response(page)


class CompanyAudit(CompanyBase):
    def get(self, request):
        qs = AuditLog.objects.filter(company=self.company)
        if request.query_params.get("search"):
            qs = qs.filter(action__icontains=request.query_params["search"])
        page = paginate(request, qs)
        page["results"] = AuditSerializer(page["results"], many=True).data
        return Response(page)


class CompanySettings(CompanyBase):
    def get(self, request):
        return Response(CompanySerializer(self.company).data)

    def patch(self, request):
        c = self.company
        for f in ("name", "timezone"):
            if f in request.data:
                setattr(c, f, str(request.data[f]).strip()[:255])
        if "allow_overallocation" in request.data:
            c.allow_overallocation = bool(request.data["allow_overallocation"])
        if "preferred_provider" in request.data:
            from .models import PlatformSettings

            choice = request.data["preferred_provider"]
            if choice and (not PlatformSettings.load().allow_company_provider_choice or choice not in (c.allowed_providers or [])):
                return Response({"detail": "That provider is not approved for your company."}, status=403)
            c.preferred_provider = choice
        if not c.name:
            return Response({"detail": "Company name is required."}, status=400)
        from django.db import IntegrityError
        try:
            c.save()
        except IntegrityError:
            return Response({"detail": "That company name is already taken."}, status=400)
        audit(request.user, "company.updated", target=c, detail={k: request.data[k] for k in request.data})
        return Response(CompanySerializer(c).data)


class Subscription(CompanyBase):
    def get(self, request):
        c = self.company
        d, m = usage(company=c)
        p = c.plan
        return Response({
            "plan": None if p is None else {"name": p.name, "price_monthly": str(p.price_monthly), "max_users": p.max_users,
                                             "daily_quota": p.daily_quota, "monthly_quota": p.monthly_quota,
                                             "analytics_level": p.analytics_level, "support_tier": p.support_tier},
            "status": c.status, "daily_limit": c.daily_limit, "monthly_limit": c.monthly_limit,
            "daily_used": d, "monthly_used": m, "seats_used": c.members.filter(is_active=True).count(),
            "note": "No payments are processed in this API.",
        })
