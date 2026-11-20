"""
Small shared DB helpers used anywhere a row needs to be claimed exclusively
(e.g. "only one process should pick up this due schedule / stuck campaign
at a time"). Kept here (rather than duplicated in scheduling/services.py
and campaigns/services.py, which can't import from each other without a
circular import) since both need the exact same behavior.
"""
from django.db import connection


def select_for_update_kwargs():
    """SKIP LOCKED only where the DB backend actually supports it (e.g. Postgres/Supabase)."""
    if connection.features.has_select_for_update_skip_locked:
        return {"skip_locked": True}
    return {}
