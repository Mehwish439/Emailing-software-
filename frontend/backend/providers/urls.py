from django.urls import path

from .views import smtp_bounce_webhook

urlpatterns = [path("smtp/bounce/", smtp_bounce_webhook, name="smtp-bounce-webhook")]
