from django.urls import path

from .views import ScheduleCreateView, ScheduleDetailView, ScheduledCampaignListView, process_due_schedules_view

urlpatterns = [
    path("scheduling/", ScheduledCampaignListView.as_view(), name="scheduling-list"),
    path("scheduling/schedule/", ScheduleCreateView.as_view(), name="scheduling-create"),
    path("scheduling/process-due/", process_due_schedules_view, name="scheduling-process-due"),
    path("scheduling/<int:pk>/", ScheduleDetailView.as_view(), name="scheduling-detail"),
]