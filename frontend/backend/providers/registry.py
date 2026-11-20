"""Provider lookup and per-campaign provider resolution."""
from django.conf import settings

from .base import ProviderConfigError
from .brevo_provider import BrevoProvider
from .smtp_provider import SmtpProvider

PROVIDERS = {"brevo": BrevoProvider, "smtp": SmtpProvider}


def get_provider(name):
    try:
        return PROVIDERS[name]()
    except KeyError as exc:
        raise ProviderConfigError(f"Unknown email provider '{name}'.") from exc


def available_providers(user):
    """
    Which providers this user may pick for a campaign (names only - never any configuration).
    Choice exists only when the platform allows company choice AND the company has an approved list.
    """
    from tenancy.models import PlatformSettings

    platform = PlatformSettings.objects.filter(pk=1).first()
    active = (platform.active_provider if platform and platform.active_provider else settings.EMAIL_PROVIDER)
    company = getattr(user, "company", None)
    options, default = [active], active
    if platform and platform.allow_company_provider_choice and company:
        approved = [p for p in (company.allowed_providers or []) if p in PROVIDERS]
        if approved:
            options = approved
            if company.preferred_provider in approved:
                default = company.preferred_provider
    return {"options": options, "default": default, "choice_allowed": len(options) > 1}


def resolve_provider_name(campaign):
    """
    Precedence (never silently falls back to a different provider):
      1. A provider already frozen on the campaign (retries/resumes keep it).
      2. The campaign owner's company choice, only if the platform allows company choice
         AND the provider is in the company's approved list.
      3. The platform's active provider (PlatformSettings.active_provider).
      4. settings.EMAIL_PROVIDER (default "brevo" -> exactly the pre-upgrade behaviour).
    """
    from tenancy.models import PlatformSettings

    if campaign.provider:
        return campaign.provider
    if campaign.requested_provider:
        # Explicit choice: honour it only while it is still permitted. Never fall back to another provider.
        if campaign.requested_provider not in available_providers(campaign.created_by)["options"]:
            raise ProviderConfigError(
                f"Provider '{campaign.requested_provider}' is no longer available to this account.")
        return campaign.requested_provider
    platform = PlatformSettings.objects.filter(pk=1).first()
    company = getattr(campaign.created_by, "company", None)
    if platform and platform.allow_company_provider_choice and company and company.preferred_provider:
        if company.preferred_provider in (company.allowed_providers or []):
            return company.preferred_provider
    if platform and platform.active_provider:
        return platform.active_provider
    return settings.EMAIL_PROVIDER
