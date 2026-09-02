import logging

from django.conf import settings
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.exceptions import ValidationAppError

from .models import ScheduledCampaign
from .serializers import CreateScheduleSerializer, ScheduledCampaignSerializer, UpdateScheduleSerializer
from .services import cancel_schedule, create_schedule, process_due_schedules, update_schedule

logger = logging.getLogger(__name__)


class ScheduledCampaignListView(generics.ListAPIView):
    """GET /api/scheduling/"""

    serializer_class = ScheduledCampaignSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ScheduledCampaign.objects.filter(campaign__created_by=self.request.user).select_related("campaign")


class ScheduleCreateView(APIView):
    """POST /api/scheduling/schedule/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateScheduleSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            schedule = create_schedule(
                campaign=serializer.validated_data["campaign"],
                scheduled_at=serializer.validated_data["scheduled_at"],
                timezone_name=serializer.validated_data["timezone"],
            )
        except ValidationAppError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ScheduledCampaignSerializer(schedule).data, status=status.HTTP_201_CREATED)


class ScheduleDetailView(APIView):
    """PUT /api/scheduling/{id}/  and  DELETE /api/scheduling/{id}/"""

    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk):
        return ScheduledCampaign.objects.filter(campaign__created_by=request.user, id=pk).first()

    def put(self, request, pk):
        schedule = self.get_object(request, pk)
        if not schedule:
            return Response({"detail": "Scheduled campaign not found."}, status=404)
        serializer = UpdateScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            schedule = update_schedule(
                schedule,
                scheduled_at=serializer.validated_data.get("scheduled_at"),
                timezone_name=serializer.validated_data.get("timezone"),
            )
        except ValidationAppError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ScheduledCampaignSerializer(schedule).data)

    def delete(self, request, pk):
        schedule = self.get_object(request, pk)
        if not schedule:
            return Response({"detail": "Scheduled campaign not found."}, status=404)
        try:
            cancel_schedule(schedule)
        except ValidationAppError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _cron_request_authorized(request):
    expected = settings.CRON_SECRET
    if not expected:
        # No secret configured — only acceptable in local/dev environments,
        # same policy as the Brevo webhook secret.
        return settings.DEBUG
    provided = request.headers.get("X-Cron-Secret") or request.query_params.get("secret")
    return provided == expected


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def process_due_schedules_view(request):
    """
    POST /api/scheduling/process-due/

    The HTTP equivalent of `python manage.py process_scheduled_campaigns` —
    for deployments without real cron access (e.g. a free-tier PaaS web
    service). Point a free external scheduler (cron-job.org, a GitHub
    Actions scheduled workflow, etc.) at this URL every minute, sending the
    shared secret as either an `X-Cron-Secret` header or a `?secret=`
    query parameter.

    Safe to call this and/or run the management command concurrently or
    repeatedly — see scheduling/services.py's process_due_schedules() for
    the row-locking that prevents any schedule from being processed twice.
    """
    if not _cron_request_authorized(request):
        logger.warning(
            "process-due: REJECTED request from %s (missing/wrong secret). "
            "If you expect an external scheduler to be calling this, this log line means it either "
            "isn't sending the secret correctly, or CRON_SECRET doesn't match on both sides.",
            request.META.get("REMOTE_ADDR"),
        )
        return Response({"detail": "Unauthorized."}, status=status.HTTP_401_UNAUTHORIZED)

    logger.info("process-due: authorized request received from %s", request.META.get("REMOTE_ADDR"))
    results = process_due_schedules()
    return Response({"processed": len(results), "results": results})


process_due_schedules_view.cls.throttle_scope = "cron"