import logging

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from common.exceptions import ValidationAppError
from contacts.models import Contact

from .models import Automation, AutomationEnrollment, AutomationExecution, AutomationStep
from .serializers import (
    AutomationEnrollmentSerializer, AutomationExecutionSerializer, AutomationSerializer, EnrollRequestSerializer,
    ExternalEventSerializer,
)
from .services import (
    activate_automation, automation_stats, enroll_contact, pause_automation, resume_automation, run_enrollment_now,
)
from .triggers import EVENT_TO_TRIGGER, handle_external_event

logger = logging.getLogger(__name__)


def _count_subquery(model, extra_filter=None):
    qs = model.objects.filter(automation=OuterRef("pk"))
    if extra_filter is not None:
        qs = qs.filter(extra_filter)
    sub = qs.order_by().values("automation").annotate(c=Count("pk")).values("c")
    return Coalesce(Subquery(sub, output_field=IntegerField()), 0)


class AutomationViewSet(viewsets.ModelViewSet):
    """
    /api/automations/ ... — every queryset is scoped to request.user, so another account's
    automations/enrollments/logs 404 exactly like the rest of the API.
    """

    serializer_class = AutomationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status", "trigger_type"]
    search_fields = ["name", "description"]
    ordering_fields = ["created_at", "name", "status"]

    def get_queryset(self):
        return (
            Automation.objects.filter(owner=self.request.user)
            .prefetch_related("steps", "steps__email_template")
            .annotate(
                enrolled_count=_count_subquery(AutomationEnrollment),
                active_count=_count_subquery(AutomationEnrollment, Q(status="active")),
                emails_sent=_count_subquery(AutomationExecution, Q(status="success", action_type="send_email")),
            )
        )

    def _respond(self, automation):
        automation = self.get_queryset().get(pk=automation.pk)
        return Response(self.get_serializer(automation).data)

    # -- lifecycle ----------------------------------------------------------
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._respond(activate_automation(self.get_object()))

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return self._respond(pause_automation(self.get_object()))

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._respond(resume_automation(self.get_object()))

    # -- enrollment ---------------------------------------------------------
    @action(detail=True, methods=["post"])
    def enroll(self, request, pk=None):
        automation = self.get_object()
        serializer = EnrollRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["all_ids"]

        contacts = {c.id: c for c in Contact.objects.filter(owner=request.user, id__in=ids)}
        enrolled, skipped, new_ids = 0, [], []
        for cid in ids:
            contact = contacts.get(cid)
            if contact is None:
                skipped.append({"contact_id": cid, "reason": "not_found"})
                continue
            res = enroll_contact(automation, contact, source="manual")
            if res["created"]:
                enrolled += 1
                new_ids.append(res["enrollment"].id)
            else:
                skipped.append({"contact_id": cid, "reason": res["reason"]})

        # Enrolling a single contact: run a zero-delay first step right away. Bigger batches are
        # left to the scheduler so this request can't hit the 30s gunicorn timeout.
        if len(new_ids) == 1:
            try:
                run_enrollment_now(new_ids[0])
            except Exception:  # noqa: BLE001
                logger.exception("Immediate run after manual enroll failed; cron will retry.")
        return Response({"enrolled": enrolled, "skipped": skipped}, status=status.HTTP_201_CREATED if enrolled else 200)

    # -- read-only sub-resources -------------------------------------------
    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        return Response(automation_stats(self.get_object()))

    @action(detail=True, methods=["get"])
    def logs(self, request, pk=None):
        automation = self.get_object()
        qs = automation.executions.select_related("contact")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(AutomationExecutionSerializer(page, many=True).data)

    @action(detail=True, methods=["get"])
    def enrollments(self, request, pk=None):
        automation = self.get_object()
        qs = automation.enrollments.select_related("contact")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(AutomationEnrollmentSerializer(page, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def external_event(request):
    """
    POST /api/automations/events/
        {"event": "cart_abandoned", "email": "customer@example.com", "contact_id": 123}

    Entry point for future Shopify / WooCommerce / webhook integrations (no fake integration is
    built here). The caller authenticates like any API client and the event is applied to THAT
    account's active automations only. The contact must already exist in the account.
    """
    serializer = ExternalEventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["event"] not in EVENT_TO_TRIGGER:
        return Response(
            {"detail": f"Unsupported event. Supported: {', '.join(sorted(EVENT_TO_TRIGGER))}."}, status=400
        )

    contacts = Contact.objects.filter(owner=request.user)
    contact = (
        contacts.filter(id=data["contact_id"]).first() if data.get("contact_id") is not None
        else contacts.filter(email__iexact=data["email"]).first()
    )
    if contact is None:
        return Response({"detail": "Contact not found."}, status=404)

    results = handle_external_event(request.user, data["event"], contact)
    return Response({
        "matched_automations": len(results),
        "enrolled": sum(1 for r in results if r["created"]),
        "results": results,
    })


external_event.cls.throttle_scope = "automation-events"
