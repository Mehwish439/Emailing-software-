from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "email", "company_name", "is_staff", "is_active", "date_joined"]
    search_fields = ["username", "email", "company_name"]
    list_filter = ["is_staff", "is_active", "date_joined"]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Company info", {"fields": ("company_name",)}),
    )
