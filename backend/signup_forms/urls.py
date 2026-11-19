# NEW FILE (Signup Forms feature)
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import SignupFormViewSet, embed_script, public_form_detail, public_form_submit

router = DefaultRouter()
router.register(r"signup-forms", SignupFormViewSet, basename="signup-form")

urlpatterns = [
    path("public/signup-forms/embed.js", embed_script, name="signup-form-embed-script"),
    path("public/signup-forms/<uuid:public_id>/", public_form_detail, name="signup-form-public-detail"),
    path("public/signup-forms/<uuid:public_id>/submit/", public_form_submit, name="signup-form-public-submit"),
] + router.urls
