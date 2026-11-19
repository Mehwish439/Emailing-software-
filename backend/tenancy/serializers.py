from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AuditLog, Company, Plan, PlatformSettings
from .quota import usage

User = get_user_model()


class PlanSerializer(serializers.ModelSerializer):
    companies = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = ["id", "name", "price_monthly", "max_users", "daily_quota", "monthly_quota", "scheduling",
                  "analytics_level", "custom_domains", "support_tier", "features", "is_active", "companies"]

    def get_companies(self, obj):
        return obj.companies.count()


class CompanySerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True, default=None)
    daily_limit = serializers.IntegerField(read_only=True)
    monthly_limit = serializers.IntegerField(read_only=True)
    users = serializers.SerializerMethodField()
    daily_used = serializers.SerializerMethodField()
    monthly_used = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = ["id", "name", "plan", "plan_name", "status", "daily_quota_override", "monthly_quota_override",
                  "daily_limit", "monthly_limit", "allowed_providers", "preferred_provider", "timezone",
                  "allow_overallocation", "users", "daily_used", "monthly_used", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_users(self, obj):
        return obj.members.filter(is_active=True).count()

    def get_daily_used(self, obj):
        return usage(company=obj)[0]

    def get_monthly_used(self, obj):
        return usage(company=obj)[1]

    def validate_allowed_providers(self, value):
        from providers.registry import PROVIDERS

        bad = [v for v in value if v not in PROVIDERS]
        if bad:
            raise serializers.ValidationError(f"Unknown provider(s): {', '.join(bad)}")
        return value


class MemberSerializer(serializers.ModelSerializer):
    daily_used = serializers.SerializerMethodField()
    monthly_used = serializers.SerializerMethodField()
    active_campaigns = serializers.SerializerMethodField()
    invite_pending = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "role", "is_active", "daily_quota", "monthly_quota",
                  "daily_used", "monthly_used", "active_campaigns", "invite_pending", "last_login", "date_joined"]
        read_only_fields = ["id", "email", "daily_used", "monthly_used", "active_campaigns", "last_login",
                            "date_joined", "invite_pending"]

    def get_daily_used(self, obj):
        return usage(user=obj)[0]

    def get_monthly_used(self, obj):
        return usage(user=obj)[1]

    def get_active_campaigns(self, obj):
        return obj.campaigns.filter(status__in=["processing", "scheduled"]).count()

    def get_invite_pending(self, obj):
        return not obj.has_usable_password()


class PlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = ["daily_budget", "monthly_budget", "rate_per_minute", "active_provider",
                  "allow_company_provider_choice", "queue_paused", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_active_provider(self, value):
        from providers.registry import PROVIDERS

        if value not in PROVIDERS:
            raise serializers.ValidationError(f"Unknown provider. Choose one of: {', '.join(PROVIDERS)}")
        return value


class AuditSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True, default=None)
    company_name = serializers.CharField(source="company.name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "created_at", "actor_email", "company_name", "action", "target_type", "target_id", "detail"]
