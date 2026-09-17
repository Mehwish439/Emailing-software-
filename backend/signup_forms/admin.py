# NEW FILE (Signup Forms feature)
from django.contrib import admin

from .models import SignupForm


@admin.register(SignupForm)
class SignupFormAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "contact_list", "is_active", "submission_count", "created_at"]
    search_fields = ["name", "owner__username", "owner__email"]
    list_filter = ["is_active", "created_at"]
