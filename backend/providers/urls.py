from django.urls import path

from .views import SendPulseSettings, SendPulseSync, SendPulseTest, sendpulse_webhook, smtp_bounce_webhook

urlpatterns = [
    path("smtp/bounce/", smtp_bounce_webhook, name="smtp-bounce-webhook"),
    path("sendpulse/webhook/", sendpulse_webhook, name="sendpulse-webhook"),
    path("sendpulse/settings/", SendPulseSettings.as_view(), name="sendpulse-settings"),
    path("sendpulse/test/", SendPulseTest.as_view(), name="sendpulse-test"),
    path("sendpulse/sync/", SendPulseSync.as_view(), name="sendpulse-sync"),
]
