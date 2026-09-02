import logging

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .webhooks import WebhookProcessingError, process_webhook_event

logger = logging.getLogger(__name__)


def _is_authorized(request):
    """
    Brevo webhooks don't support HMAC signing out of the box, so we validate
    a shared secret instead. Configure this same value as a custom header
    (recommended: 'X-Webhook-Secret') on the webhook in the Brevo dashboard,
    or append it as a query parameter (?secret=...) if custom headers aren't
    available on your Brevo plan.
    """
    expected = settings.BREVO_WEBHOOK_SECRET
    if not expected:
        # No secret configured — only acceptable in local/dev environments.
        return settings.DEBUG
    provided = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret")
    return provided == expected


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def brevo_webhook(request):
    """
    POST /api/brevo/webhook/
    Receives delivery/engagement events from Brevo and updates campaign
    recipient status, suppression lists, and the CampaignEvent log.
    Idempotent — safe to receive the same event more than once.
    """
    if not _is_authorized(request):
        logger.warning("Rejected unauthorized Brevo webhook call from %s", request.META.get("REMOTE_ADDR"))
        return Response({"detail": "Unauthorized."}, status=status.HTTP_401_UNAUTHORIZED)

    payload = request.data
    # Brevo may send a single event object or, for some configurations, a batch.
    events = payload if isinstance(payload, list) else [payload]

    results = []
    for event_payload in events:
        try:
            outcome = process_webhook_event(event_payload)
            results.append(outcome)
        except WebhookProcessingError as exc:
            logger.warning("Webhook payload rejected: %s", exc)
            results.append(f"rejected:{exc}")
        except Exception:
            logger.exception("Unexpected error processing Brevo webhook event")
            results.append("error")

    return Response({"processed": len(events), "results": results}, status=status.HTTP_200_OK)


brevo_webhook.cls.throttle_scope = "webhook"
