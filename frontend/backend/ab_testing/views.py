# NEW FILE (A/B testing feature)
"""
A/B Testing API endpoints. Function-based `@api_view`s scoped by
campaign_id, matching the existing convention analytics/views.py already
uses for its own per-campaign endpoints (campaign_analytics,
campaign_link_breakdown, campaign_report_pdf) rather than introducing a
different (e.g. nested-router) style just for this feature.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from campaigns.models import Campaign
from common.exceptions import ValidationAppError

from .serializers import CampaignVariantSerializer, SetCampaignVariantsSerializer
from .services import compute_ab_test_results, set_campaign_variants


def _get_owned_campaign(request, campaign_id):
    """Same ownership scoping CampaignViewSet.get_queryset() already applies."""
    return Campaign.objects.filter(id=campaign_id, created_by=request.user).first()


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def campaign_variants(request, campaign_id):
    """
    GET /api/campaigns/{id}/ab-variants/
        Lists this campaign's Version A / Version B (empty list if not
        configured yet, or if this isn't an A/B campaign at all).

    PUT /api/campaigns/{id}/ab-variants/
        Creates or replaces both variants in one call:
        {"variants": [
            {"label": "A", "subject": "...", "template": 3, "split_percentage": 50},
            {"label": "B", "subject": "...", "template": 4, "split_percentage": 50}
        ]}
        Only allowed while the campaign is a draft A/B campaign -- see
        ab_testing.services.set_campaign_variants for the full validation.
    """
    campaign = _get_owned_campaign(request, campaign_id)
    if campaign is None:
        return Response({"detail": "Campaign not found."}, status=404)

    if request.method == "GET":
        variants = campaign.ab_variants.all()
        return Response(CampaignVariantSerializer(variants, many=True).data)

    serializer = SetCampaignVariantsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        variants = set_campaign_variants(campaign, serializer.validated_data["variants"])
    except ValidationAppError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(CampaignVariantSerializer(variants, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def campaign_ab_results(request, campaign_id):
    """
    GET /api/campaigns/{id}/ab-results/

    Per-variant Sent/Delivered/Opened/Clicked/Bounced/Unsubscribed counts
    and rates, computed from real stored CampaignRecipient/CampaignEvent
    data (see ab_testing.services.compute_ab_test_results) -- never
    hard-coded or estimated.
    """
    campaign = _get_owned_campaign(request, campaign_id)
    if campaign is None:
        return Response({"detail": "Campaign not found."}, status=404)
    if campaign.campaign_type != Campaign.CampaignType.AB_TEST:
        return Response({"detail": "This campaign is not an A/B test campaign."}, status=400)
    return Response(compute_ab_test_results(campaign))
