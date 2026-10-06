from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AutomationViewSet, external_event

router = DefaultRouter()
router.register(r"automations", AutomationViewSet, basename="automation")

urlpatterns = [
    # Must come BEFORE router.urls so "events" isn't read as an automation pk.
    path("automations/events/", external_event, name="automation-external-event"),
] + router.urls
