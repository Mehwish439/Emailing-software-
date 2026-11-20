"""
Thin HTTP client for the SendPulse REST API (https://sendpulse.com/integrations/api).

Documented behaviour this is written against:
  * Auth: POST /oauth/access_token {grant_type: client_credentials, client_id, client_secret}
    -> {access_token, token_type: "Bearer", expires_in: 3600}. Every other call sends
    "Authorization: Bearer <token>". A token lives one hour; ask for a new one only after it expires.
  * Send: POST /smtp/emails {"email": {html (base64), text, subject, from, to, ...}}
    -> {"result": true, "id": "<message id>"}. The endpoint has NO idempotency key.
  * Limits: HTTP 429 when the per-minute/day plan quota is exceeded; error code 2020202020 for more
    than 10 requests per second.

Why error handling here is stricter than for Brevo: because there is no idempotency key, a request
that MAY have been processed must never be retried (that is how a recipient gets the same email
twice). Every failure therefore carries `may_have_been_processed`:
    False -> proven not accepted (could not connect, DNS failure, 4xx, 429, 503, auth failure)
    True  -> unknown (read timeout, connection dropped mid-request, 500/502/504, garbled success)
The provider layer turns that into temporary (retry) vs ambiguous (human review, never auto-retried).
"""
import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .base import ProviderConfigError
from .crypto import DecryptionError, EncryptionUnavailable, decrypt_json, decrypt_text, encrypt_text, encryption_available

logger = logging.getLogger(__name__)

PROVIDER_NAME = "sendpulse"
CONNECT_TIMEOUT = 5
TOKEN_REFRESH_MARGIN = timedelta(seconds=120)   # refresh a little early so a token never expires mid-batch
RATE_LIMIT_ERROR_CODE = 2020202020              # "More than 10 requests per second"


# --------------------------------------------------------------------------- configuration
@dataclass(frozen=True)
class SendPulseConfig:
    client_id: str
    client_secret: str
    webhook_secret: str = ""
    sender_name: str = ""
    sender_email: str = ""
    source: str = "none"          # "database" | "environment" | "none"
    base_url: str = "https://api.sendpulse.com"

    @property
    def fingerprint(self) -> str:
        """Identifies the credential pair a cached token belongs to (never reversible to the secret)."""
        return hashlib.sha256(f"{self.client_id}\x00{self.client_secret}".encode()).hexdigest()[:32]

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def _check_base_url(url: str):
    """Credentials are only ever sent over HTTPS (plain HTTP is accepted solely for a loopback test server)."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return
    raise ProviderConfigError("SENDPULSE_API_BASE_URL must be an https:// URL.")


def load_config() -> SendPulseConfig:
    """
    Credentials from the database (saved through the UI, encrypted) if present, else the SENDPULSE_*
    environment variables. If the database holds credentials that cannot be decrypted, this raises
    rather than quietly using the environment's -- that would silently switch SendPulse accounts.
    """
    from .models import ProviderCredential

    base_url = settings.SENDPULSE_API_BASE_URL
    row = ProviderCredential.objects.filter(provider=PROVIDER_NAME).first()
    if row and row.encrypted_secrets:
        try:
            secrets = decrypt_json(row.encrypted_secrets)
        except (DecryptionError, EncryptionUnavailable) as exc:
            raise ProviderConfigError(str(exc)) from exc
        return SendPulseConfig(
            client_id=secrets.get("client_id", ""), client_secret=secrets.get("client_secret", ""),
            webhook_secret=secrets.get("webhook_secret", "") or settings.SENDPULSE_WEBHOOK_SECRET,
            sender_name=row.sender_name or settings.SENDPULSE_SENDER_NAME,
            sender_email=row.sender_email or settings.SENDPULSE_SENDER_EMAIL,
            source="database", base_url=base_url,
        )
    have_env = bool(settings.SENDPULSE_CLIENT_ID and settings.SENDPULSE_CLIENT_SECRET)
    return SendPulseConfig(
        client_id=settings.SENDPULSE_CLIENT_ID, client_secret=settings.SENDPULSE_CLIENT_SECRET,
        webhook_secret=settings.SENDPULSE_WEBHOOK_SECRET,
        sender_name=(row.sender_name if row and row.sender_name else settings.SENDPULSE_SENDER_NAME),
        sender_email=(row.sender_email if row and row.sender_email else settings.SENDPULSE_SENDER_EMAIL),
        source="environment" if have_env else "none", base_url=base_url,
    )


def require_config() -> SendPulseConfig:
    cfg = load_config()
    if not cfg.configured:
        raise ProviderConfigError(
            "SendPulse is not configured: set the Client ID and Client Secret on the Providers & limits page "
            "(or SENDPULSE_CLIENT_ID / SENDPULSE_CLIENT_SECRET)."
        )
    _check_base_url(cfg.base_url)
    return cfg


# --------------------------------------------------------------------------- errors
class SendPulseAPIError(Exception):
    def __init__(self, message, *, status_code=None, error_code=None, payload=None,
                 may_have_been_processed=False, rate_limited=False, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.payload = payload or {}
        self.may_have_been_processed = may_have_been_processed
        self.rate_limited = rate_limited
        self.retry_after = retry_after


class SendPulseAuthError(SendPulseAPIError):
    """SendPulse refused the Client ID / Secret. Nothing was sent."""


def _failed_before_send(exc: requests.exceptions.ConnectionError) -> bool:
    """True only when the TCP/TLS connection was never established, i.e. the request cannot have been processed."""
    from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

    try:
        from urllib3.exceptions import NameResolutionError
    except ImportError:  # urllib3 < 2
        NameResolutionError = NewConnectionError
    reason = getattr(exc.args[0], "reason", None) if exc.args else None
    return isinstance(reason, (NewConnectionError, NameResolutionError, ConnectTimeoutError))


# --------------------------------------------------------------------------- token cache (per process)
_proc_lock = threading.Lock()
_proc_token = {"fp": None, "token": None, "exp": None}
_send_lock = threading.Lock()
_last_send_at = [0.0]


def reset_process_cache():
    with _proc_lock:
        _proc_token.update(fp=None, token=None, exp=None)


@dataclass
class _Token:
    value: str
    expires_at: object


class SendPulseClient:
    def __init__(self, config: SendPulseConfig = None, timeout=None):
        self.cfg = config or require_config()
        _check_base_url(self.cfg.base_url)
        self.base = self.cfg.base_url.rstrip("/")
        self.timeout = timeout or settings.SENDPULSE_HTTP_TIMEOUT

    # ---- token lifecycle -------------------------------------------------------------------
    def _fetch_token(self) -> _Token:
        """POST /oauth/access_token. No side effects at SendPulse, so any failure here is safely retryable."""
        try:
            resp = requests.post(
                f"{self.base}/oauth/access_token",
                json={"grant_type": "client_credentials", "client_id": self.cfg.client_id,
                      "client_secret": self.cfg.client_secret},
                headers={"Accept": "application/json"}, timeout=(CONNECT_TIMEOUT, self.timeout),
            )
        except requests.exceptions.RequestException as exc:
            raise SendPulseAPIError(f"Could not reach SendPulse to authenticate: {type(exc).__name__}") from exc
        body = _json_or_none(resp)
        if resp.status_code in (400, 401, 403):
            raise SendPulseAuthError(
                f"SendPulse rejected the Client ID / Secret (HTTP {resp.status_code}): {_message(body, resp)}",
                status_code=resp.status_code, payload=body if isinstance(body, dict) else {},
            )
        if resp.status_code == 429 or (isinstance(body, dict) and body.get("error_code") == RATE_LIMIT_ERROR_CODE):
            raise SendPulseAPIError("SendPulse rate limit hit while authenticating.", status_code=429, rate_limited=True)
        token = body.get("access_token") if isinstance(body, dict) else None
        if resp.status_code != 200 or not token:
            raise SendPulseAPIError(f"SendPulse authentication failed (HTTP {resp.status_code}): {_message(body, resp)}",
                                    status_code=resp.status_code)
        lifetime = int(body.get("expires_in") or 3600)
        return _Token(token, timezone.now() + timedelta(seconds=lifetime))

    def access_token(self, rejected=None) -> str:
        """
        A valid bearer token, refreshing when it is within TOKEN_REFRESH_MARGIN of expiry.
        `rejected` is a token SendPulse just answered 401 to: it is never handed back, and if another
        worker has already minted a newer one that is used instead of requesting yet another.
        Layers: per-process memory -> shared encrypted copy in the database (so every gunicorn worker
        and the cron process share one token) -> a fresh request.
        """
        now = timezone.now()
        fp = self.cfg.fingerprint
        with _proc_lock:
            c = _proc_token
            if c["fp"] == fp and c["token"] and c["token"] != rejected and c["exp"] - TOKEN_REFRESH_MARGIN > now:
                return c["token"]
        tok = self._shared_token(fp, now, rejected)
        with _proc_lock:
            _proc_token.update(fp=fp, token=tok.value, exp=tok.expires_at)
        return tok.value

    def _shared_token(self, fp, now, rejected) -> _Token:
        if not encryption_available():
            return self._fetch_token()        # env-only mode: each process keeps its own token in memory
        from .models import ProviderCredential

        with transaction.atomic():
            row, _ = ProviderCredential.objects.select_for_update().get_or_create(provider=PROVIDER_NAME)
            if row.encrypted_token and row.token_fingerprint == fp and row.token_expires_at \
                    and row.token_expires_at - TOKEN_REFRESH_MARGIN > now:
                try:
                    stored = decrypt_text(row.encrypted_token)
                except (DecryptionError, EncryptionUnavailable):
                    stored = None
                if stored and stored != rejected:
                    return _Token(stored, row.token_expires_at)
            tok = self._fetch_token()
            row.encrypted_token = encrypt_text(tok.value)
            row.token_expires_at = tok.expires_at
            row.token_fingerprint = fp
            row.save(update_fields=["encrypted_token", "token_expires_at", "token_fingerprint", "updated_at"])
            return tok

    # ---- requests --------------------------------------------------------------------------
    def _throttle(self):
        """Keep one process under SendPulse's 10 requests/second burst limit."""
        gap = settings.SENDPULSE_MIN_SEND_INTERVAL_MS / 1000.0
        if gap <= 0:
            return
        with _send_lock:
            wait = _last_send_at[0] + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_send_at[0] = time.monotonic()

    def _once(self, method, path, token, json_body, params):
        try:
            return requests.request(
                method, f"{self.base}{path}", json=json_body, params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=(CONNECT_TIMEOUT, self.timeout),
            )
        except requests.exceptions.ConnectTimeout as exc:
            raise SendPulseAPIError("Timed out connecting to SendPulse.") from exc
        except requests.exceptions.ConnectionError as exc:
            if _failed_before_send(exc):
                raise SendPulseAPIError("Could not connect to SendPulse.") from exc
            raise SendPulseAPIError("The connection to SendPulse dropped mid-request.",
                                    may_have_been_processed=True) from exc
        except requests.exceptions.RequestException as exc:   # ReadTimeout, ChunkedEncodingError, SSLError, ...
            raise SendPulseAPIError(f"No complete answer from SendPulse ({type(exc).__name__}).",
                                    may_have_been_processed=True) from exc

    def request(self, method, path, *, json=None, params=None, throttle=False):
        token = self.access_token()
        for attempt in (1, 2):
            if throttle:
                self._throttle()
            resp = self._once(method, path, token, json, params)
            if resp.status_code == 401 and attempt == 1:
                # An expired/revoked token: the request was NOT processed, so re-authenticating and
                # re-sending once cannot duplicate anything.
                token = self.access_token(rejected=token)
                continue
            return self._parse(resp)

    @staticmethod
    def _parse(resp):
        status = resp.status_code
        body = _json_or_none(resp)
        if 200 <= status < 300:
            if body is None and resp.content:
                raise SendPulseAPIError("SendPulse returned a success status with an unreadable body.",
                                        status_code=status, may_have_been_processed=True)
            return body if body is not None else {}
        code = body.get("error_code") if isinstance(body, dict) else None
        retry_after = _retry_after(resp)
        limited = status == 429 or code == RATE_LIMIT_ERROR_CODE
        # 503 means "not processed". Other 5xx can come from a gateway AFTER the message was queued.
        may = status >= 500 and status != 503
        raise SendPulseAPIError(
            _message(body, resp), status_code=status, error_code=code,
            payload=body if isinstance(body, dict) else {"message": resp.text[:500]},
            may_have_been_processed=may and not limited, rate_limited=limited, retry_after=retry_after,
        )

    # ---- endpoints -------------------------------------------------------------------------
    def send_email(self, email_object: dict) -> dict:
        """POST /smtp/emails. Returns the parsed response; the caller interprets `result` / `id`."""
        return self.request("POST", "/smtp/emails", json={"email": email_object}, throttle=True)

    def user_info(self):
        return self.request("GET", "/user/info")

    def smtp_senders(self):
        return self.request("GET", "/smtp/senders")

    def balance_detail(self):
        return self.request("GET", "/user/balance/detail")

    def email_info(self, message_id):
        return self.request("GET", f"/smtp/emails/{message_id}")


# --------------------------------------------------------------------------- helpers
def _json_or_none(resp):
    try:
        return resp.json()
    except ValueError:
        return None


def _message(body, resp) -> str:
    if isinstance(body, dict):
        for key in ("message", "error_description", "error", "error_code"):
            if body.get(key):
                return str(body[key])[:300]
    return (resp.text or f"HTTP {resp.status_code}")[:300]


def _retry_after(resp):
    try:
        return int(resp.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return None
