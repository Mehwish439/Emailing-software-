from django.urls import path

from .views import brevo_webhook

urlpatterns = [
    path("webhook/", brevo_webhook, name="brevo-webhook"),
]
