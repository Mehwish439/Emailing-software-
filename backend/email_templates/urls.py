from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    EmailTemplateViewSet,
    list_starter_templates,
    template_image_content,
    upload_template_image,
)

router = DefaultRouter()
router.register(r"templates", EmailTemplateViewSet, basename="template")

urlpatterns = [
    path("templates/starters/", list_starter_templates, name="template-starters"),
    path("templates/images/", upload_template_image, name="template-image-upload"),
    path("templates/images/<int:pk>/content/", template_image_content, name="template-image-content"),
] + router.urls