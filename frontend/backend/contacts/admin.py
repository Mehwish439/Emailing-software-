from django.contrib import admin

from .models import Contact, ContactList


@admin.register(ContactList)
class ContactListAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "contact_count", "created_at"]
    search_fields = ["name", "owner__username", "owner__email"]
    list_filter = ["created_at"]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["email", "first_name", "last_name", "status", "owner", "created_at"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    list_filter = ["status", "created_at"]
    autocomplete_fields = []
