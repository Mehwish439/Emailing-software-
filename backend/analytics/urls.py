from django.urls import path

from .views import (
    all_campaigns_report_pdf,
    campaign_analytics,
    campaign_link_breakdown,
    campaign_report_pdf,
    dashboard_summary,
)

urlpatterns = [
    path("analytics/dashboard/", dashboard_summary, name="analytics-dashboard"),
    path("analytics/report.pdf", all_campaigns_report_pdf, name="analytics-all-campaigns-pdf"),
    path("analytics/campaigns/<int:campaign_id>/", campaign_analytics, name="analytics-campaign"),
    path("analytics/campaigns/<int:campaign_id>/links/", campaign_link_breakdown, name="analytics-campaign-links"),
    path("analytics/campaigns/<int:campaign_id>/report.pdf", campaign_report_pdf, name="analytics-campaign-pdf"),
]