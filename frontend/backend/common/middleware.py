import logging
import time

logger = logging.getLogger(__name__)


class ExceptionLoggingMiddleware:
    """Logs any exception that escapes view processing without exposing it to the client."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.path)
        return None  # let Django/DRF continue normal error handling


class RequestTimingMiddleware:
    """
    Logs server-side wall-clock time for every /api/ request: how long Django
    itself took to build the response (view logic + all DB/Brevo calls it
    made), as opposed to whatever time was spent before the request even
    reached Django (DNS, TLS, Render's own routing, a cold-start boot) or
    after the response left Django (network back to the browser).

    Useful for the exact question "is the slowness Django/Supabase, or is it
    Render/network?" — compare this log's duration_ms against what the
    browser's Network tab reports for the same request. If the browser shows
    3000ms but this logs 40ms, the extra ~3s happened outside Django
    entirely (very likely a Render cold start). If the numbers are close,
    the time is genuinely being spent inside this request — check which
    endpoint and look at what it queries.

    Intentionally left permanently enabled (not just "temporary" debug
    logging) — it's cheap (one time.monotonic() call per request) and this
    kind of visibility is worth keeping in a free/low-resource deployment
    where cold starts and remote-DB latency are ongoing realities, not a
    one-time thing to diagnose and remove.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        logger.info(
            "%s %s -> %s in %sms",
            request.method, request.path, response.status_code, duration_ms,
        )
        return response