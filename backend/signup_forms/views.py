# NEW FILE (Signup Forms feature)
import logging

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .embed import EMBED_SCRIPT
from .models import SignupForm
from .serializers import PublicSignupFormSerializer, SignupFormSerializer, SignupFormSubmitSerializer
from .services import submit_signup_form

logger = logging.getLogger(__name__)


class SignupFormViewSet(viewsets.ModelViewSet):
    """
    Authenticated management CRUD (spec section #7/#8). Activate/deactivate
    is just a normal PATCH of `is_active` — no separate endpoint is needed
    for it, matching how ContactList/Tag/Campaign already expose their own
    boolean/status fields through the standard update action rather than a
    bespoke action per field.
    """

    serializer_class = SignupFormSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SignupForm.objects.filter(owner=self.request.user).select_related("contact_list").prefetch_related(
            "tags"
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


# ---------------------------------------------------------------------------
# Public endpoints — no authentication, reachable from any external website
# embedding a form. See signup_forms/cors.py for why these two paths (and
# only these two) allow cross-origin requests from any origin.
#
# SECURITY: these must never expose anything beyond what's required to
# render/submit the one selected form — no owner info, no other forms, no
# contact_list/tag names, no other contacts, no Brevo credentials (this
# feature never touches Brevo at all — see the FINAL RESPONSE's Brevo
# section). PublicSignupFormSerializer (not SignupFormSerializer) enforces
# that allowlist for the detail endpoint; the submit endpoint below never
# echoes back anything but a plain success/error message.
# ---------------------------------------------------------------------------


def _get_active_form_or_none(public_id):
    return SignupForm.objects.filter(public_id=public_id, is_active=True).first()


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def public_form_detail(request, public_id):
    """
    GET /api/public/signup-forms/<public_id>/

    Returns 404 for both "no such form" and "form exists but is
    deactivated" — deliberately indistinguishable, so a deactivated form's
    id leaks no more information than a made-up one.
    """
    form = _get_active_form_or_none(public_id)
    if form is None:
        return Response({"detail": "This form is not available."}, status=status.HTTP_404_NOT_FOUND)
    return Response(PublicSignupFormSerializer(form).data)


public_form_detail.cls.throttle_scope = "signup-form"


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def public_form_submit(request, public_id):
    """
    POST /api/public/signup-forms/<public_id>/submit/

    Creates/updates a Contact under the form owner's account and attaches
    the form's configured list/tags (spec sections #2/#3). Never requires
    the visitor to authenticate — the public_id + is_active check is the
    entire access control for this endpoint, matching the unsubscribe
    endpoint's model (contacts/views.py's unsubscribe_via_token).
    """
    form = _get_active_form_or_none(public_id)
    if form is None:
        return Response({"detail": "This form is not available."}, status=status.HTTP_404_NOT_FOUND)

    serializer = SignupFormSubmitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    if data.get("hp_field"):
        # Honeypot tripped — a real visitor's browser never fills this in
        # (see embed.py). Return the normal success response so the bot
        # doesn't learn it was detected, but never touch the database.
        logger.info("Honeypot triggered on signup form public_id=%s — submission ignored.", public_id)
        return Response({"message": form.success_message}, status=status.HTTP_201_CREATED)

    submit_signup_form(
        form,
        email=data["email"],
        first_name=data.get("first_name", "") if form.collect_first_name else "",
        last_name=data.get("last_name", "") if form.collect_last_name else "",
    )

    return Response({"message": form.success_message}, status=status.HTTP_201_CREATED)


public_form_submit.cls.throttle_scope = "signup-form-submit"


@api_view(["GET"])
@permission_classes([AllowAny])
def embed_script(request):
    """
    GET /api/public/signup-forms/embed.js

    Static, dependency-free embed script — see embed.py's module
    docstring. No throttle: it's a static file, not a data endpoint, and
    is expected to be fetched by every page-load of every site embedding
    any form.
    """
    response = HttpResponse(EMBED_SCRIPT, content_type="application/javascript")
    response["Cache-Control"] = "public, max-age=3600"
    return response
