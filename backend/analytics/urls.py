from django.urls import path

from .views import campaign_analytics, campaign_link_breakdown, dashboard_summary

urlpatterns = [
    path("analytics/dashboard/", dashboard_summary, name="analytics-dashboard"),
    path("analytics/campaigns/<int:campaign_id>/", campaign_analytics, name="analytics-campaign"),
    path("analytics/campaigns/<int:campaign_id>/links/", campaign_link_breakdown, name="analytics-campaign-links"),
]