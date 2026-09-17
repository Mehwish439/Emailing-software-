# NEW FILE (A/B testing feature)
from django.contrib import admin

from .models import CampaignVariant


@admin.register(CampaignVariant)
class CampaignVariantAdmin(admin.ModelAdmin):
    list_display = ("campaign", "label", "subject", "template", "split_percentage", "created_at")
    list_filter = ("label",)
    search_fields = ("campaign__name", "subject")
