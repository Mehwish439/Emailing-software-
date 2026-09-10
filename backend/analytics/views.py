from django.http import FileResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from campaigns.models import Campaign

from .pdf_reports import build_all_campaigns_report_pdf, build_campaign_report_pdf
from .services import compute_campaign_analytics, compute_campaign_link_breakdown, compute_dashboard_summary


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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def campaign_link_breakdown(request, campaign_id):
    """
    GET /api/analytics/campaigns/{id}/links/

    Per-URL click breakdown (never one combined campaign-level number), and
    a corrected unsubscribe view that separates link REQUESTS (every GET —
    human or automated scanner, never a side effect) from CONFIRMED
    unsubscribes (an actual status change). See analytics/services.py's
    compute_campaign_link_breakdown for the full explanation of what this
    can and can't tell you, and why.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id, created_by=request.user)
    except Campaign.DoesNotExist:
        return Response({"detail": "Campaign not found."}, status=404)
    return Response(compute_campaign_link_breakdown(campaign))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def campaign_report_pdf(request, campaign_id):
    """
    GET /api/analytics/campaigns/{id}/report.pdf

    Downloadable PDF of this campaign's number breakdown only (Sent,
    Delivered, Opened, ... and the rate percentages) — no per-recipient
    log/list, matching the same summary shown on the campaign's own
    analytics view.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id, created_by=request.user)
    except Campaign.DoesNotExist:
        return Response({"detail": "Campaign not found."}, status=404)

    analytics = compute_campaign_analytics(campaign)
    buffer = build_campaign_report_pdf(campaign, analytics)
    filename = f"campaign-{campaign.id}-report.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type="application/pdf")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def all_campaigns_report_pdf(request):
    """
    GET /api/analytics/report.pdf

    Downloadable PDF covering every one of this user's campaigns — one row
    per campaign with its own Sent/Delivered/Opened/Clicked/Bounced/
    Unsubscribed counts, plus the overall totals at the top. Numbers only,
    same principle as the single-campaign report above.
    """
    campaigns = Campaign.objects.filter(created_by=request.user).order_by("-created_at")
    rows = []
    for campaign in campaigns:
        a = compute_campaign_analytics(campaign)
        rows.append(
            {
                "name": campaign.name,
                "status": campaign.get_status_display(),
                "sent": a["sent"],
                "delivered": a["delivered"],
                "opened": a["opened"],
                "clicked": a["clicked"],
                "bounced": a["soft_bounced"] + a["hard_bounced"],
                "unsubscribed": a["unsubscribed"],
            }
        )

    summary = compute_dashboard_summary(request.user)
    buffer = build_all_campaigns_report_pdf(rows, summary)
    return FileResponse(buffer, as_attachment=True, filename="campaigns-report.pdf", content_type="application/pdf")