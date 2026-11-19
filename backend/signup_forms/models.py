# NEW FILE (Signup Forms feature)
"""
Website Signup Forms.

A SignupForm is a small, hosted opt-in form a user can embed on an
external website (see embed.py for the actual embed snippet/script). It
deliberately does NOT introduce a new audience/grouping system: submitting
one just creates-or-updates a normal contacts.Contact and attaches it to an
existing ContactList and/or Tag set, exactly like a manual "add to list" or
a CSV import would (see contacts/services.py, contacts/views.py's
add_to_list). This keeps a signup form's contacts fully visible everywhere
the rest of the app already looks — Contacts page, campaigns, segments —
with no parallel data model to keep in sync.

A ContactList is used as the target audience rather than a Segment: a
Segment's membership is *computed* from tags/list/status (see
contacts/models.py's Segment docstring) — there is no operation to
"manually add a contact to a segment", so it cannot be what a signup form
adds a new contact into. Selecting tags on the signup form is still the
right way to make a submission flow into a segment: any Segment already
filtering on those tags will pick the new contact up automatically.
"""
import uuid

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel
from contacts.models import ContactList, Tag


class SignupForm(TimeStampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="signup_forms")

    # Public, non-sequential identifier used in the embed code/public API —
    # never the DB primary key, so embedding a form on a public website
    # never exposes this owner's row count or lets one guess at other
    # forms' ids.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Where a submission's contact is attached. Both optional so a form can
    # be tag-only, list-only, or both — but see validate() below, which
    # requires at least one; otherwise a submission would create a contact
    # attached to nothing at all.
    contact_list = models.ForeignKey(
        ContactList, on_delete=models.SET_NULL, null=True, blank=True, related_name="signup_forms"
    )
    tags = models.ManyToManyField(Tag, related_name="signup_forms", blank=True)

    # Contact fields collected. Email is always required by every signup
    # form and is therefore not a toggle — only first/last name are
    # optional per-form, matching the spec's "Initially support: Email
    # (required), First Name (optional), Last Name (optional)".
    collect_first_name = models.BooleanField(default=True)
    collect_last_name = models.BooleanField(default=True)

    # Basic customization only (spec explicitly rules out a drag-and-drop
    # form builder).
    button_text = models.CharField(max_length=60, default="Subscribe")
    success_message = models.CharField(
        max_length=200, default="Thanks for subscribing! Please check your inbox to confirm."
    )

    is_active = models.BooleanField(default=True)

    # A denormalized counter rather than a full submission-log table:
    # requirement #7 only ever needs "how many submissions", not a
    # per-submission audit trail, so a log model would be scope creep here.
    # Incremented with F("submission_count") + 1 (see views.py) to stay
    # correct under concurrent submissions.
    submission_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "name")

    def __str__(self):
        return self.name
