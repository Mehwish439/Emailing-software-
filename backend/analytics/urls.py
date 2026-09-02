from django.urls import path

from .views import campaign_analytics, dashboard_summary

urlpatterns = [
    path("analytics/dashboard/", dashboard_summary, name="analytics-dashboard"),
    path("analytics/campaigns/<int:campaign_id>/", campaign_analytics, name="analytics-campaign"),
]
