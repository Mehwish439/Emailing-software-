"""
Symmetric encryption for provider credentials that administrators save through the UI.

The codebase had no secret-storage mechanism before this (Brevo's key is only ever an environment
variable), so this adds the smallest thing that is actually safe: Fernet (AES-128-CBC + HMAC-SHA256,
authenticated) with a key that lives ONLY in the environment (PROVIDER_CREDENTIALS_KEY), never in the
database next to the ciphertext.

* Several comma-separated keys are accepted. The first encrypts; all of them decrypt, so a key can be
  rotated without losing stored credentials.
* If no valid key is configured, saving credentials through the UI is refused with a clear message.
  Nothing falls back to a key derived from SECRET_KEY: rotating SECRET_KEY must never silently make
  stored provider credentials unreadable, and a leaked SECRET_KEY must not also unlock them.
"""
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class EncryptionUnavailable(Exception):
    """No usable PROVIDER_CREDENTIALS_KEY is configured."""


class DecryptionError(Exception):
    """Stored ciphertext cannot be decrypted with the configured key(s)."""


def _fernet() -> MultiFernet:
    raw = getattr(settings, "PROVIDER_CREDENTIALS_KEY", "") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise EncryptionUnavailable(
            "PROVIDER_CREDENTIALS_KEY is not set, so credentials cannot be stored in the database. "
            "Set it (see docs/SENDPULSE_INTEGRATION.md) or use the SENDPULSE_* environment variables."
        )
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError) as exc:
        raise EncryptionUnavailable(
            "PROVIDER_CREDENTIALS_KEY is not a valid Fernet key (it must be 32 url-safe base64-encoded bytes)."
        ) from exc


def encryption_available() -> bool:
    try:
        _fernet()
        return True
    except EncryptionUnavailable:
        return False


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Stored credentials could not be decrypted. PROVIDER_CREDENTIALS_KEY has changed or was removed; "
            "restore the previous key or re-enter the credentials."
        ) from exc


def encrypt_json(data: dict) -> str:
    return encrypt_text(json.dumps(data, separators=(",", ":")))


def decrypt_json(token: str) -> dict:
    try:
        return json.loads(decrypt_text(token))
    except ValueError as exc:  # corrupt plaintext; treat like an unreadable secret
        raise DecryptionError("Stored credentials are corrupt.") from exc
