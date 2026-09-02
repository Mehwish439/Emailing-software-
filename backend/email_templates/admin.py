from django.contrib import admin

from .models import EmailTemplate


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "subject", "created_by", "created_at"]
    search_fields = ["name", "subject"]
    list_filter = ["created_at"]
