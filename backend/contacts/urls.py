from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ContactListViewSet, ContactViewSet, unsubscribe_via_token

router = DefaultRouter()
router.register(r"contacts", ContactViewSet, basename="contact")
router.register(r"contact-lists", ContactListViewSet, basename="contact-list")

urlpatterns = [
    path("unsubscribe/<str:token>/", unsubscribe_via_token, name="unsubscribe"),
] + router.urls