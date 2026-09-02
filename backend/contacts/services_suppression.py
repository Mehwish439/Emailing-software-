"""
Helpers for checking/adding suppressions. Kept in its own module (rather than
services.py) so campaign-sending code can import just the suppression check
without pulling in CSV-import dependencies.
"""
from .models import Suppression


def filter_out_suppressed(contact_queryset):
    """Given a Contact queryset, exclude any contact whose email is on the suppression list."""
    suppressed_emails = set(Suppression.objects.values_list("email", flat=True))
    if not suppressed_emails:
        return contact_queryset
    return contact_queryset.exclude(email__in=suppressed_emails)


def add_suppression(email, reason):
    Suppression.objects.get_or_create(email=email.lower(), defaults={"reason": reason})


def is_suppressed(email):
    return Suppression.objects.filter(email__iexact=email).exists()
