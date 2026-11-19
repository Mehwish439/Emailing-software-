from rest_framework.routers import DefaultRouter

from .views import CampaignViewSet

router = DefaultRouter()
router.register(r"campaigns", CampaignViewSet, basename="campaign")

urlpatterns = router.urls
