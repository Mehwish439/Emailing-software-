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
