import hashlib
import hmac
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .bounces import ingest_report

logger = logging.getLogger(__name__)
MAX_BODY = 1_000_000


@csrf_exempt
@require_POST
def smtp_bounce_webhook(request):
    """
    POST /api/providers/smtp/bounce/   (called by the bounce-forwarder on the SMTP server)
    Body: the raw bounce/ARF message. Header X-Signature: hex HMAC-SHA256(body, SMTP_BOUNCE_WEBHOOK_SECRET).
    The secret is mandatory: with none configured the endpoint refuses everything.
    """
    secret = settings.SMTP_BOUNCE_WEBHOOK_SECRET
    if not secret:
        return HttpResponse("Bounce webhook is not configured.", status=503)
    body = request.body
    if len(body) > MAX_BODY:
        return HttpResponse("Payload too large.", status=413)
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Signature", "")):
        logger.warning("Rejected SMTP bounce webhook with bad signature from %s", request.META.get("REMOTE_ADDR"))
        return HttpResponse("Unauthorized.", status=401)
    results = ingest_report(body, request.headers.get("X-Envelope-Recipient", ""))
    return JsonResponse({"results": results})


# =============================================================================== SendPulse
import hmac  # noqa: E402
import json as _json  # noqa: E402

from django.core.validators import validate_email  # noqa: E402
from django.core.exceptions import ValidationError as DjangoValidationError  # noqa: E402
from django.utils import timezone as _tz  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

from tenancy.permissions import IsPlatformAdmin  # noqa: E402
from tenancy.services import audit  # noqa: E402

from .base import ProviderConfigError  # noqa: E402
from .crypto import DecryptionError, EncryptionUnavailable, decrypt_json, encrypt_json, encryption_available  # noqa: E402
from .models import ProviderCredential  # noqa: E402
from .sendpulse_client import PROVIDER_NAME, load_config, reset_process_cache  # noqa: E402
from .sendpulse_provider import SendPulseProvider  # noqa: E402
from .sendpulse_webhooks import ingest_event, sync_recent, verify_signature  # noqa: E402


@csrf_exempt
@require_POST
def sendpulse_webhook(request):
    """
    POST /api/providers/sendpulse/webhook/
    Verified with X-Signature (HMAC-SHA256 of the raw body) OR an X-Webhook-Secret header (as Brevo's webhook does);
    both use the secret saved on the SendPulse card.
    With no secret configured the endpoint refuses everything (fail closed, unlike Brevo's dev fallback).
    Responses are chosen for SendPulse's retry behaviour: 401 bad signature, 400 unreadable body,
    500 if processing failed (it will retry; ingestion is idempotent), 200 otherwise.
    """
    try:
        secret = load_config().webhook_secret
    except ProviderConfigError:
        secret = ""
    if not secret:
        return HttpResponse("SendPulse webhook is not configured.", status=503)
    body = request.body                      # read BEFORE anything parses it: the signature covers exact bytes
    if len(body) > MAX_BODY:
        return HttpResponse("Payload too large.", status=413)
    # Two accepted proofs, both using the SAME configured secret:
    #  1. SendPulse's own signature: X-Signature = sha256=HMAC-SHA256(raw body, secret)
    #  2. Like the Brevo webhook: a shared secret sent in a custom header (X-Webhook-Secret), which can be added
    #     in SendPulse's "Additional headers" field. Constant-time comparison; never accepted in the URL.
    shared = request.headers.get("X-Webhook-Secret", "")
    shared_ok = bool(shared) and hmac.compare_digest(shared.encode("utf-8"), secret.encode("utf-8"))
    if not (shared_ok or verify_signature(body, request.headers.get("X-Signature", ""), secret)):
        logger.warning("Rejected SendPulse webhook with bad credentials from %s", request.META.get("REMOTE_ADDR"))
        return HttpResponse("Unauthorized.", status=401)
    try:
        payload = _json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("Invalid JSON.", status=400)
    events = payload if isinstance(payload, list) else [payload]
    results = []
    try:
        for ev in events:
            results.append(ingest_event(ev, source="webhook") if isinstance(ev, dict) else "rejected:not-an-object")
    except Exception:  # noqa: BLE001
        logger.exception("Error processing SendPulse webhook")
        return HttpResponse("Processing error.", status=500)
    return JsonResponse({"processed": len(events), "results": results})


def _status_block(row, cfg):
    if not cfg.configured:
        state = "not_configured"
    elif row is None or row.last_test_ok is None:
        state = "untested"
    else:
        state = "connected" if row.last_test_ok else "failed"
    return {"state": state, "last_tested_at": row.last_tested_at if row else None,
            "detail": row.last_test_detail if row else ""}


def _mask(value):
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else ("•" * len(value))


class SendPulseSettings(APIView):
    """
    GET/PUT /api/providers/sendpulse/settings/   (platform administrators only)
    Nothing secret is ever returned: only whether each secret is set, a masked client-id hint, and status.
    PUT: omitted/blank secret fields keep their stored value; send a value to replace it.
    """

    permission_classes = [IsPlatformAdmin]

    def _payload(self):
        try:
            cfg = load_config()
            error = ""
        except ProviderConfigError as exc:
            from .sendpulse_client import SendPulseConfig
            cfg, error = SendPulseConfig("", "", source="database"), str(exc)
        row = ProviderCredential.objects.filter(provider=PROVIDER_NAME).first()
        from django.conf import settings
        return {
            "client_id_hint": _mask(cfg.client_id) if cfg.client_id else "",
            "client_id_set": bool(cfg.client_id), "client_secret_set": bool(cfg.client_secret),
            "webhook_secret_set": bool(cfg.webhook_secret),
            "sender_name": cfg.sender_name, "sender_email": cfg.sender_email,
            "source": cfg.source, "encryption_available": encryption_available(),
            "status": _status_block(row, cfg), "config_error": error,
            "webhook_url": f"{settings.BACKEND_BASE_URL}/api/providers/sendpulse/webhook/",
        }

    def get(self, request):
        return Response(self._payload())

    def put(self, request):
        d = request.data
        errors = {}
        email = (d.get("sender_email") or "").strip()
        if email:
            try:
                validate_email(email)
            except DjangoValidationError:
                errors["sender_email"] = ["Enter a valid email address."]
        new_secrets = {k: (d.get(k) or "").strip() for k in ("client_id", "client_secret", "webhook_secret")}
        if any(new_secrets.values()) and not encryption_available():
            errors["detail"] = ["PROVIDER_CREDENTIALS_KEY is not set on the server, so credentials cannot be stored "
                                "securely. Set it, or use the SENDPULSE_* environment variables."]
        if errors:
            return Response(errors, status=400)
        row, _ = ProviderCredential.objects.get_or_create(provider=PROVIDER_NAME)
        changed = []
        if any(new_secrets.values()):
            try:
                current = decrypt_json(row.encrypted_secrets) if row.encrypted_secrets else {}
            except (DecryptionError, EncryptionUnavailable):
                current = {}          # unreadable old value: the admin is replacing it
            for k, v in new_secrets.items():
                if v:
                    current[k] = v
                    changed.append(k)
            if not (current.get("client_id") and current.get("client_secret")):
                return Response({"detail": ["Client ID and Client Secret are both required."]}, status=400)
            row.encrypted_secrets = encrypt_json(current)
            row.client_id_hint = _mask(current["client_id"])
            if "client_id" in changed or "client_secret" in changed:
                row.encrypted_token, row.token_expires_at, row.token_fingerprint = "", None, ""
                row.last_test_ok, row.last_test_detail, row.last_tested_at = None, "", None
        for field in ("sender_name", "sender_email"):
            if field in d:
                setattr(row, field, (d.get(field) or "").strip())
                changed.append(field)
        row.updated_by = request.user
        row.save()
        reset_process_cache()
        audit(request.user, "provider.sendpulse_settings_changed", company=None, target=row, detail={"fields": changed})
        return Response(self._payload())


class SendPulseTest(APIView):
    """POST /api/providers/sendpulse/test/ -- read-only connectivity/auth check. Sends no email."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        result = SendPulseProvider().test_connection()
        row, _ = ProviderCredential.objects.get_or_create(provider=PROVIDER_NAME)
        row.last_test_ok, row.last_tested_at = result["ok"], _tz.now()
        row.last_test_detail = (result.get("detail") or "")[:500]
        row.save(update_fields=["last_test_ok", "last_tested_at", "last_test_detail", "updated_at"])
        return Response(result)


class SendPulseSync(APIView):
    """POST /api/providers/sendpulse/sync/ -- pull delivery/open/click status for recent messages."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        try:
            return Response(sync_recent(limit=min(int(request.data.get("limit", 25)), 50)))
        except ProviderConfigError as exc:
            return Response({"detail": str(exc)}, status=400)