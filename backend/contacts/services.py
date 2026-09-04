import csv
import io
import logging

from django.db import transaction

from common.validators import is_valid_email

from .models import Contact

logger = logging.getLogger(__name__)

REQUIRED_HEADERS = {"email"}
OPTIONAL_HEADERS = {"first_name", "last_name", "phone"}

# Contact fields that always exist as dedicated model columns (as opposed to
# arbitrary imported columns, which live in Contact.attributes). Used to seed
# the "Insert Variable" dropdown in the template editor alongside whatever
# columns a given CSV import contributes. Keep in sync with
# email_templates.rendering.get_contact_merge_fields().
STANDARD_MERGE_FIELDS = ["first_name", "last_name", "email", "phone", "full_name"]


class CSVImportError(Exception):
    pass


# Invisible/encoding-artifact characters that sometimes end up glued to a
# cell's value when contact lists are copy-pasted out of Excel/Sheets into a
# plain-text file (e.g. a stray non-breaking space or zero-width space
# right before an email address). Python's str.strip() already removes
# regular whitespace, but not these -- so a perfectly valid email like
# "info@example.com" can otherwise get rejected as invalid just because of
# one leftover invisible character.
_INVISIBLE_CHARS = "\u00a0\u200b\u200c\u200d\ufeff"


def _clean(value):
    if value is None:
        return ""
    return value.strip(_INVISIBLE_CHARS + " \t\r\n")


def _sniff_dialect(raw_text):
    """
    Contact exports don't always come out as comma-delimited -- pasting a
    spreadsheet into a plain-text file commonly produces a TAB-delimited
    file instead (Excel's copy behavior), and some exports use semicolons.
    Sniff the real delimiter from a sample of the file instead of assuming
    comma, falling back to comma if sniffing can't tell.
    """
    sample = raw_text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        return csv.excel  # csv module's default comma dialect


def import_contacts_from_csv(owner, file_obj, list_ids=None):
    """
    Parses an uploaded CSV/TSV file and creates Contact records for `owner`.

    Expected columns: first_name, last_name, email, phone (first_name/last_name/phone optional).
    The delimiter (comma, tab, or semicolon) is auto-detected rather than
    assumed, since spreadsheet exports commonly come out tab-delimited.

    Returns a dict: {imported, duplicates, invalid, total_processed, errors}
    """
    try:
        raw = file_obj.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVImportError("The file must be UTF-8 encoded CSV.") from exc

    dialect = _sniff_dialect(raw)
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    if reader.fieldnames is None:
        raise CSVImportError("The CSV file appears to be empty.")

    headers = {h.strip().lower() for h in reader.fieldnames}
    if not REQUIRED_HEADERS.issubset(headers):
        raise CSVImportError(f"CSV must contain at least these columns: {', '.join(REQUIRED_HEADERS)}")

    existing_emails = set(
        Contact.objects.filter(owner=owner).values_list("email", flat=True)
    )
    seen_in_file = set()

    imported, duplicates, invalid, total = 0, 0, 0, 0
    errors = []
    to_create = []

    for row_number, row in enumerate(reader, start=2):  # header is row 1
        total += 1
        normalized = {k.strip().lower(): _clean(v) for k, v in row.items() if k}
        email = normalized.get("email", "").lower()

        if not is_valid_email(email):
            invalid += 1
            errors.append(f"Row {row_number}: invalid email '{email}'")
            continue

        if email in existing_emails or email in seen_in_file:
            duplicates += 1
            continue

        seen_in_file.add(email)

        # Preserve EVERY column from the uploaded file, under its original
        # header text (e.g. "First_name", "COMPANY WEBSITE", "POSTAL
        # ADDRESS"), as a per-contact attribute -- not just the handful of
        # columns (first_name/last_name/phone) that map to dedicated model
        # fields above. This is what makes any imported column available as
        # a {{variable}} template placeholder later (see
        # email_templates/rendering.py), without hard-coding which columns
        # are supported.
        attributes = {}
        for raw_header in reader.fieldnames:
            if not raw_header or not raw_header.strip():
                continue
            attributes[raw_header.strip()] = _clean(row.get(raw_header))

        to_create.append(
            Contact(
                owner=owner,
                email=email,
                first_name=normalized.get("first_name", ""),
                last_name=normalized.get("last_name", ""),
                phone=normalized.get("phone", ""),
                status=Contact.Status.ACTIVE,
                attributes=attributes,
            )
        )

    with transaction.atomic():
        created_contacts = Contact.objects.bulk_create(to_create)
        imported = len(created_contacts)
        if list_ids:
            through_lists = owner.contact_lists.filter(id__in=list_ids)
            for contact in created_contacts:
                contact.lists.set(through_lists)

    return {
        "imported": imported,
        "duplicates": duplicates,
        "invalid": invalid,
        "total_processed": total,
        "errors": errors[:100],  # cap to avoid huge payloads
    }