from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.services import compute_campaign_analytics
from common.exceptions import BrevoAPIError, ValidationAppError

from .models import Campaign
from .serializers import CampaignSerializer, SendTestEmailSerializer


class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status"]
    search_fields = ["name", "subject"]
    ordering_fields = ["created_at", "name", "sent_at"]

    def get_queryset(self):
        return Campaign.objects.filter(created_by=self.request.user).select_related("template")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        campaign = self.get_object()
        if campaign.status in (Campaign.Status.PROCESSING, Campaign.Status.SENT):
            return Response(
                {"detail": "Sent or currently-processing campaigns cannot be deleted."}, status=400
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        campaign = self.get_object()
        clone = Campaign.objects.create(
            name=f"{campaign.name} (Copy)",
            subject=campaign.subject,
            sender_name=campaign.sender_name,
            sender_email=campaign.sender_email,
            template=campaign.template,
            created_by=request.user,
            status=Campaign.Status.DRAFT,
        )
        clone.contact_lists.set(campaign.contact_lists.all())
        return Response(CampaignSerializer(clone, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        from email_templates.rendering import render_template_for_contact

        campaign = self.get_object()
        # Render with a real contact from the campaign's selected lists when
        # one exists, so the preview shows actual {{variable}} values (and
        # never raw {{...}} placeholders) instead of just the raw template.
        sample_contact = campaign.eligible_contacts_queryset().first()
        if sample_contact is not None:
            subject, html_content = render_template_for_contact(
                campaign.subject,
                campaign.template.html_content,
                sample_contact,
                extra_fields={"unsubscribe_url": "#"},
            )
        else:
            subject, html_content = campaign.subject, campaign.template.html_content

        return Response(
            {
                "subject": subject,
                "sender_name": campaign.sender_name,
                "sender_email": campaign.sender_email,
                "html_content": html_content,
            }
        )

    @action(detail=True, methods=["post"], url_path="test")
    def send_test(self, request, pk=None):
        self.throttle_scope = "test-email"
        from brevo.services import send_test_email

        campaign = self.get_object()
        serializer = SendTestEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            send_test_email(campaign, serializer.validated_data["test_email"])
        except BrevoAPIError as exc:
            return Response({"detail": str(exc)}, status=502)
        return Response({"detail": f"Test email sent to {serializer.validated_data['test_email']}."})

    @action(detail=True, methods=["post"], url_path="send-now")
    def send_now(self, request, pk=None):
        from .services import send_campaign_now

        campaign = self.get_object()
        try:
            # send_campaign_now() runs synchronously and returns the final,
            # freshly-reloaded Campaign — use that (not the pre-send object
            # still held in `campaign`) so the response reflects the actual
            # outcome (sent/failed), not the pre-send draft/scheduled state.
            campaign = send_campaign_now(campaign)
        except ValidationAppError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(CampaignSerializer(campaign, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        campaign = self.get_object()
        return Response(compute_campaign_analytics(campaign))

    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        from .serializers import CampaignRecipientSerializer

        campaign = self.get_object()
        page = self.paginate_queryset(campaign.recipients.select_related("contact").all())
        serializer = CampaignRecipientSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)