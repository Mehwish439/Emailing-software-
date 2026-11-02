"""
Multi-tenant hierarchy: Platform -> Company -> User, plus the quota ledger and
audit log.

Design notes (see docs/UPGRADE_NOTES.md):
  * Everything here is ADDITIVE. Existing users have company=None and are
    treated as "standalone" tenants: user + platform limits still apply, the
    company level is simply skipped. Nothing existing is migrated or deleted.
  * A NULL limit means "unlimited at this level" so behaviour is unchanged until
    an administrator configures a limit.
  * The database is the source of truth for quota; Redis/Celery never hold it.
"""
from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class Plan(TimeStampedModel):
    class Analytics(models.TextChoices):
        BASIC = "basic", "Basic"
        ADVANCED = "advanced", "Advanced"
        FULL = "full", "Full"

    name = models.CharField(max_length=80, unique=True)
    price_monthly = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    max_users = models.PositiveIntegerField(default=5)
    daily_quota = models.PositiveIntegerField(default=1000)
    monthly_quota = models.PositiveIntegerField(default=20000)
    scheduling = models.BooleanField(default=True)
    analytics_level = models.CharField(max_length=10, choices=Analytics.choices, default=Analytics.BASIC)
    custom_domains = models.PositiveIntegerField(default=0)
    support_tier = models.CharField(max_length=40, default="Email")
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)  # False = archived

    class Meta:
        ordering = ["price_monthly", "name"]

    def __str__(self):
        return self.name


class Company(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIAL = "trial", "Trial"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=255, unique=True)
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.PROTECT, related_name="companies")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    # Super-admin overrides; NULL -> fall back to the plan's allowance.
    daily_quota_override = models.PositiveIntegerField(null=True, blank=True)
    monthly_quota_override = models.PositiveIntegerField(null=True, blank=True)
    # Providers this company is allowed to choose between (subset of registry names).
    allowed_providers = models.JSONField(default=list, blank=True)
    preferred_provider = models.CharField(max_length=30, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    # Deliberate over-allocation policy: when False (default) the sum of members' daily
    # quotas may not exceed the company's daily allowance.
    allow_overallocation = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    @property
    def daily_limit(self):
        if self.daily_quota_override is not None:
            return self.daily_quota_override
        return self.plan.daily_quota if self.plan_id else None

    @property
    def monthly_limit(self):
        if self.monthly_quota_override is not None:
            return self.monthly_quota_override
        return self.plan.monthly_quota if self.plan_id else None

    @property
    def can_send(self):
        return self.status != self.Status.SUSPENDED


class PlatformSettings(models.Model):
    """Singleton (pk=1). Platform-wide capacity, rate limit and provider policy."""

    daily_budget = models.PositiveIntegerField(null=True, blank=True)
    monthly_budget = models.PositiveIntegerField(null=True, blank=True)
    # Global submission rate. NULL = unlimited. This is a SOFTWARE guard only; it
    # never raises real capacity and must be set from the host's written policy.
    rate_per_minute = models.PositiveIntegerField(null=True, blank=True)
    active_provider = models.CharField(max_length=30, default="brevo")
    allow_company_provider_choice = models.BooleanField(default=False)
    queue_paused = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "platform settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform settings"


class QuotaLedger(TimeStampedModel):
    """
    One row per recipient message (never per campaign). OneToOne on the
    recipient means a retry can never be charged twice.
    """

    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CONSUMED = "consumed", "Consumed"
        RELEASED = "released", "Released"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quota_entries")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="quota_entries")
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="quota_entries")
    recipient = models.OneToOneField("campaigns.CampaignRecipient", on_delete=models.CASCADE, related_name="quota_entry")
    credits = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=10, choices=State.choices, default=State.RESERVED)
    usage_date = models.DateField()

    class Meta:
        indexes = [
            models.Index(fields=["user", "usage_date", "state"]),
            models.Index(fields=["company", "usage_date", "state"]),
            models.Index(fields=["usage_date", "state"]),
        ]


class AuditLog(models.Model):
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "-created_at"])]


class JobHeartbeat(models.Model):
    """Last-run record for scheduled jobs (cron command or Celery beat) so the super admin can see staleness."""

    name = models.CharField(max_length=80, unique=True)
    last_run_at = models.DateTimeField()
    last_status = models.CharField(max_length=20, default="ok")
    detail = models.CharField(max_length=300, blank=True)
    runs = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} @ {self.last_run_at:%Y-%m-%d %H:%M:%S} ({self.last_status})"
