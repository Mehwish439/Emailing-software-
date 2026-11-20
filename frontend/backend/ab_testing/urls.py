# NEW FILE (A/B testing feature)
from django.urls import path

from .views import campaign_ab_results, campaign_variants

urlpatterns = [
    path("campaigns/<int:campaign_id>/ab-variants/", campaign_variants, name="campaign-ab-variants"),
    path("campaigns/<int:campaign_id>/ab-results/", campaign_ab_results, name="campaign-ab-results"),
]
