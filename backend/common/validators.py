import re

from django.core.exceptions import ValidationError

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    if not value:
        return False
    return bool(EMAIL_REGEX.match(value.strip()))


def validate_email_format(value: str):
    if not is_valid_email(value):
        raise ValidationError(f"'{value}' is not a valid email address.")
