from django.contrib import admin

from .models import Campaign, CampaignRecipient


class CampaignRecipientInline(admin.TabularInline):
    model = CampaignRecipient
    extra = 0
    readonly_fields = ["contact", "status", "sent_at"]
    can_delete = False


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "created_by", "recipient_count", "sent_at", "created_at"]
    search_fields = ["name", "subject", "sender_email"]
    list_filter = ["status", "created_at"]
    inlines = [CampaignRecipientInline]


@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ["contact", "campaign", "status", "sent_at"]
    list_filter = ["status"]
    search_fields = ["contact__email", "campaign__name"]
