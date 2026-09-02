from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from campaigns.models import Campaign

from .services import compute_campaign_analytics, compute_dashboard_summary


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    """GET /api/analytics/dashboard/"""
    return Response(compute_dashboard_summary(request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def campaign_analytics(request, campaign_id):
    """GET /api/analytics/campaigns/{id}/"""
    try:
        campaign = Campaign.objects.get(id=campaign_id, created_by=request.user)
    except Campaign.DoesNotExist:
        return Response({"detail": "Campaign not found."}, status=404)
    return Response(compute_campaign_analytics(campaign))
