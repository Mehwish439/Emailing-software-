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
            campaign_type=campaign.campaign_type,
            created_by=request.user,
            status=Campaign.Status.DRAFT,
        )
        clone.contact_lists.set(campaign.contact_lists.all())
        if campaign.campaign_type == Campaign.CampaignType.AB_TEST:
            # Clone each A/B variant too, so a duplicated A/B campaign is
            # immediately ready to edit/send rather than needing its
            # variants rebuilt from scratch.
            from ab_testing.models import CampaignVariant

            for variant in campaign.ab_variants.all():
                CampaignVariant.objects.create(
                    campaign=clone,
                    label=variant.label,
                    subject=variant.subject,
                    template=variant.template,
                    split_percentage=variant.split_percentage,
                )
        return Response(CampaignSerializer(clone, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        from email_templates.rendering import render_template_for_contact

        campaign = self.get_object()

        # For an A/B campaign, ?variant=A or ?variant=B previews that
        # specific version's own subject/template instead of the
        # campaign-level (Version-A-mirrored) default -- this is what lets
        # the frontend preview BOTH versions (see the feature's Step 1 --
        # "The user should be able to preview both versions").
        variant_label = (request.query_params.get("variant") or "").upper() or None
        variant = None
        if variant_label:
            if campaign.campaign_type != Campaign.CampaignType.AB_TEST:
                return Response({"detail": "This campaign is not an A/B test campaign."}, status=400)
            variant = campaign.ab_variants.filter(label=variant_label).first()
            if variant is None:
                return Response({"detail": f"Version {variant_label} is not configured for this campaign yet."}, status=404)

        subject_source = variant.subject if variant else campaign.subject
        html_source = variant.template.html_content if variant else campaign.template.html_content

        # Render with a real contact from the campaign's selected lists when
        # one exists, so the preview shows actual {{variable}} values (and
        # never raw {{...}} placeholders) instead of just the raw template.
        sample_contact = campaign.eligible_contacts_queryset().first()
        if sample_contact is not None:
            subject, html_content = render_template_for_contact(
                subject_source,
                html_source,
                sample_contact,
                extra_fields={"unsubscribe_url": "#"},
            )
        else:
            subject, html_content = subject_source, html_source

        return Response(
            {
                "subject": subject,
                "sender_name": campaign.sender_name,
                "sender_email": campaign.sender_email,
                "html_content": html_content,
                "variant": variant_label,
            }
        )

    @action(detail=True, methods=["post"], url_path="test")
    def send_test(self, request, pk=None):
        self.throttle_scope = "test-email"
        from brevo.services import send_test_email

        campaign = self.get_object()
        serializer = SendTestEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        variant = None
        variant_label = serializer.validated_data.get("variant")
        if variant_label:
            if campaign.campaign_type != Campaign.CampaignType.AB_TEST:
                return Response({"detail": "This campaign is not an A/B test campaign."}, status=400)
            variant = campaign.ab_variants.filter(label=variant_label).first()
            if variant is None:
                return Response({"detail": f"Version {variant_label} is not configured for this campaign yet."}, status=400)

        try:
            send_test_email(campaign, serializer.validated_data["test_email"], variant=variant)
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
    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        """
        GET /api/campaigns/{id}/recipients/?recipient_status=delivered
        GET /api/campaigns/{id}/recipients/?recipient_status=delivered,opened,clicked

        Optional ?recipient_status= filter (comma-separated for more than
        one) — matches CampaignRecipient.Status values. Named
        "recipient_status", NOT "status": this ViewSet's own
        filterset_fields = ["status"] filters CAMPAIGNS by their status
        (e.g. GET /api/campaigns/?status=sent), and self.get_object() below
        runs that same filtering automatically — a plain "?status=" here
        would collide with it and get validated against Campaign's OWN
        status choices instead of CampaignRecipient's, causing a confusing
        400 "not one of the available choices" error.

        Comma-separated support matters for e.g. "Delivered": a recipient
        who progressed further to "opened"/"clicked" was still delivered,
        so the frontend's Delivered stat card filters by all three at once
        rather than missing them.
        """
        from .serializers import CampaignRecipientSerializer

        campaign = self.get_object()
        queryset = campaign.recipients.select_related("contact").order_by("id")
        status_filter = request.query_params.get("recipient_status")
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            queryset = queryset.filter(status__in=statuses)
        page = self.paginate_queryset(queryset)
        serializer = CampaignRecipientSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)