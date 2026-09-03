from django.contrib import admin

from .models import EmailTemplate, TemplateImage


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "subject", "created_by", "created_at"]
    search_fields = ["name", "subject"]
    list_filter = ["created_at"]


@admin.register(TemplateImage)
class TemplateImageAdmin(admin.ModelAdmin):
    # Deliberately excludes the raw `data` field from every view below —
    # it's a binary blob, not useful to render in admin, and large enough
    # per-row that listing it out would slow the changelist down for no
    # benefit.
    list_display = ["original_filename", "content_type", "size_bytes", "owner", "created_at"]
    search_fields = ["original_filename", "owner__username", "owner__email"]
    list_filter = ["content_type", "created_at"]
    readonly_fields = ["content_type", "original_filename", "size_bytes", "owner", "created_at", "updated_at"]
    exclude = ["data"]