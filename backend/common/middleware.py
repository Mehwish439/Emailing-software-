import logging

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
