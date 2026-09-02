from django.contrib import admin

from .models import ScheduledCampaign


@admin.register(ScheduledCampaign)
class ScheduledCampaignAdmin(admin.ModelAdmin):
    list_display = ["campaign", "scheduled_at", "timezone", "status", "created_at"]
    list_filter = ["status", "timezone"]
    search_fields = ["campaign__name"]
