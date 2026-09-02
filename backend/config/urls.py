from django.contrib import admin
from django.urls import include, path

from common.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health_check, name="health-check"),

    path("api/auth/", include("accounts.urls")),
    path("api/", include("contacts.urls")),
    path("api/", include("email_templates.urls")),
    path("api/", include("campaigns.urls")),
    path("api/", include("scheduling.urls")),
    path("api/", include("analytics.urls")),
    path("api/brevo/", include("brevo.urls")),
]
