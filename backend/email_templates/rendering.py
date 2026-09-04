"""
Single reusable place for turning an (subject, html_content) template pair
plus a Contact into the actual per-recipient email content.

Used by every code path that needs to fill in {{variable}} merge tags:
template preview, campaign preview, test-email sends, send-now, and
scheduled sending (which itself just calls send-now's underlying service).
Keeping this in one function means every one of those call sites treats a
missing/unknown variable and unicode/whitespace the same way.
"""
import re

from contacts.services import STANDARD_MERGE_FIELDS

# Matches {{variable}}, {{ variable }}, {{Variable Name}} etc. Whitespace
# immediately inside the braces is ignored; the variable name itself is
# matched exactly (case-sensitive), since imported column names are stored
# and displayed exactly as they appeared in the source file.
MERGE_TAG_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def get_contact_merge_fields(contact):
    """
    Builds the {variable_name: value} dict for one contact: the standard
    Contact model fields plus every column preserved from that contact's
    CSV/Excel import (contact.attributes) -- see contacts/services.py.

    `contact` only needs to duck-type a real Contact (first_name, last_name,
    email, phone, full_name, attributes) -- brevo/services.py relies on this
    to build a placeholder "sample contact" for test sends when a campaign
    has no real recipients yet.
    """
    fields = {name: getattr(contact, name, "") or "" for name in STANDARD_MERGE_FIELDS}
    attributes = getattr(contact, "attributes", None)
    if isinstance(attributes, dict):
        # Imported columns take precedence -- e.g. if the CSV had its own
        # "email" or "First_name" column, that exact original value (and
        # header spelling) is what the template variable resolves to.
        fields.update(attributes)
    return fields


def render_merge_tags(text, merge_fields):
    """
    Replaces every {{variable}} in `text` using `merge_fields`. A variable
    with no matching field (e.g. a column only some imported contacts had)
    is replaced with an empty string -- never left as raw {{...}} and never
    raises, so one contact's missing field can't crash the whole send.
    """
    if not text:
        return text

    def _replace(match):
        value = merge_fields.get(match.group(1), "")
        return "" if value is None else str(value)

    return MERGE_TAG_PATTERN.sub(_replace, text)


def render_template_for_contact(subject, html_content, contact, extra_fields=None):
    """
    Renders both `subject` and `html_content` for one `contact`.

    `extra_fields` lets a caller merge in values that aren't part of the
    contact's own data (e.g. brevo/services.py passing a per-send
    `unsubscribe_url`) without those values needing to live on the Contact
    model.
    """
    merge_fields = get_contact_merge_fields(contact)
    if extra_fields:
        merge_fields.update(extra_fields)
    return (
        render_merge_tags(subject, merge_fields),
        render_merge_tags(html_content, merge_fields),
    )
