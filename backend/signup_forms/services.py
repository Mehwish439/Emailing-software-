# NEW FILE (Signup Forms feature)
"""
Business logic for processing a public signup-form submission. Mirrors the
layering the rest of the app already uses (see brevo/services.py's module
docstring, campaigns/services.py) — the view stays thin and this is where
the actual "create/update contact, attach list+tags" work happens.
"""
import logging

from django.db import transaction
from django.db.models import F

from contacts.models import Contact

logger = logging.getLogger(__name__)


def emit_contact_signup_event(contact, form):
    """
    Placeholder hook for future Marketing Automation (spec section #11):
    a real automation engine would subscribe to a "contact_signup" event
    here (e.g. via Celery/a signal/an outbox table) and trigger things
    like a welcome-email send. Deliberately just logs today — no
    automation system exists yet — but every submission already flows
    through this single choke point, so wiring up real automation later
    is additive and never requires touching submit_signup_form() again.
    """
    logger.info("contact_signup event: contact_id=%s form_id=%s owner_id=%s", contact.id, form.id, form.owner_id)


@transaction.atomic
def submit_signup_form(form, *, email, first_name="", last_name=""):
    """
    Creates-or-updates the submitting Contact under the form owner's
    account, attaches the form's configured list/tags, bumps the form's
    submission_count, and fires the (currently log-only) signup event.

    Never raises for a "contact already exists" case (see spec section
    #3) — that's the normal, expected path here, not an error.
    """
    owner = form.owner

    contact, created = Contact.objects.get_or_create(
        owner=owner,
        email=email,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "status": Contact.Status.ACTIVE,
        },
    )

    if not created:
        # Fill in blanks only — never overwrite a name the contact (or an
        # earlier import/manual edit) already has, and never touch
        # `status` here: a previously-unsubscribed contact re-submitting
        # this form gets attached to the new list/tags below, but isn't
        # silently flipped back to ACTIVE by this endpoint alone. Sending
        # already excludes suppressed contacts regardless (see
        # contacts/services_suppression.py / campaigns/models.py's
        # eligible_contacts_queryset), so this is safe either way.
        update_fields = []
        if first_name and not contact.first_name:
            contact.first_name = first_name
            update_fields.append("first_name")
        if last_name and not contact.last_name:
            contact.last_name = last_name
            update_fields.append("last_name")
        if update_fields:
            contact.save(update_fields=[*update_fields, "updated_at"])

    if form.contact_list_id:
        contact.lists.add(form.contact_list_id)

    tag_ids = list(form.tags.values_list("id", flat=True))
    if tag_ids:
        contact.tags.add(*tag_ids)

    SignupForm = form.__class__
    SignupForm.objects.filter(pk=form.pk).update(submission_count=F("submission_count") + 1)

    emit_contact_signup_event(contact, form)

    return contact, created
