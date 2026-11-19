from django.contrib import admin

from .models import CampaignEvent


@admin.register(CampaignEvent)
class CampaignEventAdmin(admin.ModelAdmin):
    list_display = ["event_type", "contact", "campaign", "timestamp"]
    list_filter = ["event_type", "timestamp"]
    search_fields = ["contact__email", "campaign__name", "dedupe_key"]
