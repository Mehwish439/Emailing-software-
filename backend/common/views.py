from django.db import connections
from django.db.utils import OperationalError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """
    GET /api/health/
    Reports the health of the API along with its database connection.
    There is no Redis/Celery in this architecture, so only the database is
    checked. Returns HTTP 200 when healthy, HTTP 503 when the database is
    unavailable.
    """
    db_status = "connected"
    try:
        connections["default"].cursor()
    except OperationalError:
        db_status = "unavailable"

    healthy = db_status == "connected"

    payload = {
        "status": "healthy" if healthy else "degraded",
        "database": db_status,
    }
    return Response(payload, status=200 if healthy else 503)