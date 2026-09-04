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


def import_contacts_from_csv(owner, file_obj, list_ids=None):
    """
    Parses an uploaded CSV file and creates Contact records for `owner`.

    Expected columns: first_name, last_name, email, phone (first_name/last_name/phone optional).

    Returns a dict: {imported, duplicates, invalid, total_processed, errors}
    """
    try:
        raw = file_obj.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVImportError("The file must be UTF-8 encoded CSV.") from exc

    reader = csv.DictReader(io.StringIO(raw))
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
        normalized = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
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
            attributes[raw_header.strip()] = (row.get(raw_header) or "").strip()

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