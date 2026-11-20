
import csv
import io
import logging

from django.db import transaction
from django.db.models.functions import Lower

from common.validators import is_valid_email

from .models import Contact

logger = logging.getLogger(__name__)

REQUIRED_HEADERS = {"email"}
OPTIONAL_HEADERS = {"first_name", "last_name", "phone"}

STANDARD_MERGE_FIELDS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "full_name",
]

# Import configuration
BATCH_SIZE = 500
RELATION_BATCH_SIZE = 1000
ERROR_LIMIT = 100

# Invisible characters sometimes introduced by Excel/Sheets.
_INVISIBLE_CHARS = "\u00a0\u200b\u200c\u200d\ufeff"


class CSVImportError(Exception):
    """Raised when an uploaded CSV cannot be imported."""
    pass


def _clean(value):
    """Remove surrounding whitespace and invisible characters."""
    if value is None:
        return ""

    return value.strip(_INVISIBLE_CHARS + " \t\r\n")


def _sniff_dialect(sample):
    """
    Detect comma, tab or semicolon delimiters.
    Defaults to comma when detection fails.
    """
    try:
        return csv.Sniffer().sniff(
            sample,
            delimiters=",\t;"
        )
    except csv.Error:
        return csv.excel


def _get_existing_emails(owner, emails):
    """
    Fetch existing contact emails for one owner in a single
    case-insensitive database query.
    """
    if not emails:
        return set()

    return set(
        Contact.objects.filter(owner=owner)
        .annotate(normalized_email=Lower("email"))
        .filter(normalized_email__in=emails)
        .values_list("normalized_email", flat=True)
    )


def _assign_contact_lists(created_contacts, list_ids):
    """
    Efficiently assign contact lists using the automatic
    many-to-many through table.

    For custom through models, retain Django's relationship
    manager behavior.
    """
    if not created_contacts or not list_ids:
        return

    m2m_field = Contact._meta.get_field("lists")
    through = m2m_field.remote_field.through

    if not through._meta.auto_created:
        # Preserve compatibility with custom through models.
        # Their additional required fields must be handled
        # according to their actual model definition.
        for contact in created_contacts:
            contact.lists.set(list_ids)

        return

    source_field = through._meta.get_field(
        m2m_field.m2m_field_name()
    )

    target_field = through._meta.get_field(
        m2m_field.m2m_reverse_field_name()
    )

    relations = (
        through(
            **{
                source_field.attname: contact.pk,
                target_field.attname: list_id,
            }
        )
        for contact in created_contacts
        for list_id in list_ids
    )

    through.objects.bulk_create(
        relations,
        batch_size=RELATION_BATCH_SIZE,
        ignore_conflicts=True,
    )


def _save_batch(owner, contacts, list_ids):
    """
    Save one batch of contacts.

    Returns:
        imported_count, duplicate_count
    """
    if not contacts:
        return 0, 0

    emails = {
        contact.email.lower()
        for contact in contacts
    }

    existing_emails = _get_existing_emails(
        owner,
        emails
    )

    new_contacts = [
        contact
        for contact in contacts
        if contact.email.lower() not in existing_emails
    ]

    duplicate_count = len(contacts) - len(new_contacts)

    if not new_contacts:
        return 0, duplicate_count

    # Each batch is atomic. If contact creation or list assignment
    # fails, the batch is rolled back.
    with transaction.atomic():

        created_contacts = Contact.objects.bulk_create(
            new_contacts,
            batch_size=BATCH_SIZE,
        )

        _assign_contact_lists(
            created_contacts,
            list_ids
        )

    imported_count = len(created_contacts)

    logger.info(
        "CSV import batch completed: "
        "owner=%s imported=%s duplicates=%s",
        owner.pk,
        imported_count,
        duplicate_count,
    )

    return imported_count, duplicate_count


def import_contacts_from_csv(owner, file_obj, list_ids=None):
    """
    Import contacts from CSV/TSV files using memory-efficient
    batch processing.

    Supported encodings:
        - UTF-8
        - UTF-8 with BOM

    Supported delimiters:
        - Comma
        - Tab
        - Semicolon

    Required column:
        - email

    Optional standard columns:
        - first_name
        - last_name
        - phone

    All other CSV columns are preserved in Contact.attributes.

    Returns:
        {
            imported,
            duplicates,
            invalid,
            total_processed,
            errors
        }
    """

    imported = 0
    duplicates = 0
    invalid = 0
    total = 0

    errors = []
    batch = []
    batch_seen = set()

    try:
        # Wrap the uploaded binary file in a UTF-8 text reader.
        # This avoids reading and decoding the entire file at once.
        text_file = io.TextIOWrapper(
            file_obj,
            encoding="utf-8-sig",
            errors="strict",
            newline="",
        )

        # Read a small sample to identify the delimiter.
        sample = text_file.read(8192)

        if not sample.strip():
            raise CSVImportError(
                "The CSV file appears to be empty."
            )

        dialect = _sniff_dialect(sample)

        # Return to the beginning after reading the sample.
        text_file.seek(0)

        reader = csv.DictReader(
            text_file,
            dialect=dialect
        )

        if not reader.fieldnames:
            raise CSVImportError(
                "The CSV file appears to be empty."
            )

        # Validate headers.
        headers = {
            header.strip().lower()
            for header in reader.fieldnames
            if header and header.strip()
        }

        if not REQUIRED_HEADERS.issubset(headers):
            raise CSVImportError(
                "CSV must contain at least an email column."
            )

        # Only assign lists belonging to this owner's account.
        valid_list_ids = []

        if list_ids:
            valid_list_ids = list(
                owner.contact_lists.filter(
                    id__in=list_ids
                ).values_list("id", flat=True)
            )

        def flush_batch():
            nonlocal imported, duplicates

            if not batch:
                return

            imported_count, duplicate_count = _save_batch(
                owner,
                batch,
                valid_list_ids,
            )

            imported += imported_count
            duplicates += duplicate_count

            batch.clear()
            batch_seen.clear()

        # Process CSV records incrementally.
        for row_number, row in enumerate(reader, start=2):

            total += 1

            normalized = {
                key.strip().lower(): _clean(value)
                for key, value in row.items()
                if key
            }

            email = normalized.get(
                "email", ""
            ).lower()

            # Validate email.
            if not is_valid_email(email):

                invalid += 1

                if len(errors) < ERROR_LIMIT:
                    errors.append(
                        f"Row {row_number}: "
                        f"invalid email '{email}'"
                    )

                continue

            # Detect duplicates inside the current batch.
            if email in batch_seen:
                duplicates += 1
                continue

            batch_seen.add(email)

            # Preserve every uploaded CSV column as a contact
            # attribute for dynamic email template variables.
            attributes = {}

            for raw_header in reader.fieldnames:

                if not raw_header or not raw_header.strip():
                    continue

                attributes[raw_header.strip()] = _clean(
                    row.get(raw_header)
                )

            contact = Contact(
                owner=owner,
                email=email,
                first_name=normalized.get(
                    "first_name", ""
                ),
                last_name=normalized.get(
                    "last_name", ""
                ),
                phone=normalized.get(
                    "phone", ""
                ),
                status=Contact.Status.ACTIVE,
                attributes=attributes,
            )

            batch.append(contact)

            # Save when the batch reaches the configured size.
            if len(batch) >= BATCH_SIZE:
                flush_batch()

        # Save the remaining records.
        flush_batch()

        logger.info(
            "CSV import completed: "
            "owner=%s total=%s imported=%s "
            "duplicates=%s invalid=%s",
            owner.pk,
            total,
            imported,
            duplicates,
            invalid,
        )

        return {
            "imported": imported,
            "duplicates": duplicates,
            "invalid": invalid,
            "total_processed": total,
            "errors": errors[:ERROR_LIMIT],
        }

    except UnicodeDecodeError as exc:

        logger.warning(
            "CSV encoding error for owner=%s: %s",
            owner.pk,
            exc,
        )

        raise CSVImportError(
            "The file must be UTF-8 encoded CSV. "
            "Please export it as CSV UTF-8."
        ) from exc

    except csv.Error as exc:

        logger.warning(
            "CSV parsing error for owner=%s: %s",
            owner.pk,
            exc,
        )

        raise CSVImportError(
            f"Invalid CSV format: {exc}"
        ) from exc

    except CSVImportError:
        raise

    except Exception:

        logger.exception(
            "Unexpected CSV import failure for owner=%s",
            owner.pk,
        )

        raise
