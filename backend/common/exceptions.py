import logging

from django.db import DatabaseError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class ServiceUnavailableError(Exception):
    """Raised when an upstream dependency (e.g. Brevo) is unreachable."""


class BrevoAPIError(Exception):
    """Raised when the Brevo API returns an error response."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class ValidationAppError(Exception):
    """Raised for domain-level validation failures outside of serializers."""


def custom_exception_handler(exc, context):
    """
    Wraps DRF's default exception handler so that:
      - Known DRF exceptions keep their standard formatted response.
      - Domain-specific exceptions map to sensible HTTP codes.
      - Unexpected exceptions never leak internal details / stack traces.
    """
    response = exception_handler(exc, context)

    if response is not None:
        if not isinstance(response.data, dict) or "detail" not in response.data:
            response.data = {"detail": response.data}
        return response

    if isinstance(exc, BrevoAPIError):
        logger.error("Brevo API error: %s", exc)
        return Response(
            {"detail": "The email delivery provider returned an error. Please try again."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, ServiceUnavailableError):
        logger.error("Service unavailable: %s", exc)
        return Response(
            {"detail": "A required background service is temporarily unavailable. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, ValidationAppError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, DatabaseError):
        logger.exception("Infrastructure error")
        return Response(
            {"detail": "A server error occurred. Our team has been notified."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Unknown/unexpected exception — never expose the raw message or traceback.
    logger.exception("Unhandled exception in view")
    return Response(
        {"detail": "An unexpected error occurred. Please try again later."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )