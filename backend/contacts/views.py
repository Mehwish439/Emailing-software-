
import logging

from django.core import signing
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Contact, ContactList
from .serializers import (
    BulkDeleteSerializer,
    CSVImportResultSerializer,
    ContactListSerializer,
    ContactSerializer,
    ListMembershipSerializer,
)
from .services import (
    STANDARD_MERGE_FIELDS,
    CSVImportError,
    import_contacts_from_csv,
)
from .services_suppression import add_suppression
from .unsubscribe import parse_unsubscribe_token

logger = logging.getLogger(__name__)


class ContactListViewSet(viewsets.ModelViewSet):
    serializer_class = ContactListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["created_at", "name"]

    def get_queryset(self):
        return ContactList.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["status", "lists"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    ordering_fields = [
        "created_at",
        "email",
        "first_name",
        "last_name",
    ]

    def get_queryset(self):
        return Contact.objects.filter(
            owner=self.request.user
        ).prefetch_related("lists")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        deleted_count, _ = Contact.objects.filter(
            owner=request.user,
            id__in=serializer.validated_data["ids"],
        ).delete()

        return Response(
            {"deleted": deleted_count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="import-csv")
    def import_csv(self, request):
        file_obj = request.FILES.get("file")

        if not file_obj:
            return Response(
                {
                    "detail": (
                        "A CSV file must be uploaded under "
                        "the 'file' field."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        list_ids = (
            request.data.getlist("list_ids")
            if hasattr(request.data, "getlist")
            else request.data.get("list_ids", [])
        )

        try:
            result = import_contacts_from_csv(
                request.user,
                file_obj,
                list_ids=list_ids,
            )
        except CSVImportError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            CSVImportResultSerializer(result).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="merge-fields")
    def merge_fields(self, request):
        """
        GET /api/contacts/merge-fields/

        Returns every template variable available for this user's
        contacts: standard Contact fields plus every column preserved
        from CSV/Excel imports in Contact.attributes.
        """

        fields = list(STANDARD_MERGE_FIELDS)
        seen = set(fields)

        attributes_by_contact = (
            Contact.objects.filter(owner=request.user)
            .exclude(attributes={})
            .values_list("attributes", flat=True)
        )

        for attributes in attributes_by_contact:
            if not isinstance(attributes, dict):
                continue

            for key in attributes.keys():
                if key not in seen:
                    seen.add(key)
                    fields.append(key)

        return Response({"fields": fields})

    @action(detail=False, methods=["post"], url_path="add-to-list")
    def add_to_list(self, request):
        list_id = request.data.get("list_id")

        contact_list = ContactList.objects.filter(
            owner=request.user,
            id=list_id,
        ).first()

        if not contact_list:
            return Response(
                {"detail": "Contact list not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ListMembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        contacts = Contact.objects.filter(
            owner=request.user,
            id__in=serializer.validated_data["contact_ids"],
        )

        for contact in contacts:
            contact.lists.add(contact_list)

        return Response(
            {
                "added": contacts.count(),
                "list": contact_list.id,
            }
        )

    @action(detail=False, methods=["post"], url_path="remove-from-list")
    def remove_from_list(self, request):
        list_id = request.data.get("list_id")

        contact_list = ContactList.objects.filter(
            owner=request.user,
            id=list_id,
        ).first()

        if not contact_list:
            return Response(
                {"detail": "Contact list not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ListMembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        contacts = Contact.objects.filter(
            owner=request.user,
            id__in=serializer.validated_data["contact_ids"],
        )

        for contact in contacts:
            contact.lists.remove(contact_list)

        return Response(
            {
                "removed": contacts.count(),
                "list": contact_list.id,
            }
        )


def _unsubscribe_page(
    title,
    message,
    ok=True,
    confirm_form_token=None,
):
    """
    Render the unsubscribe confirmation/result page.

    GET requests only display the confirmation page.
    They never unsubscribe the contact.

    The actual unsubscribe happens only through POST.
    """

    color = "#059669" if ok else "#dc2626"
    form_html = ""

    if confirm_form_token:
        form_html = f"""
<form method="POST" action="?confirm=1" style="margin-top:20px;">
  <input type="hidden" name="csrfmiddlewaretoken" value="">
  <button type="submit" style="background:#dc2626;color:#fff;border:none;border-radius:8px;
    padding:12px 24px;font-size:14px;font-weight:600;cursor:pointer;">
    Confirm unsubscribe
  </button>
</form>
"""

    return HttpResponse(
        f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
  body {{
    font-family: -apple-system, system-ui, sans-serif;
    background: #f8fafc;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
  }}

  .card {{
    background: #fff;
    border-radius: 12px;
    padding: 40px;
    max-width: 420px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}

  h1 {{
    color: {color};
    font-size: 20px;
    margin: 0 0 12px;
  }}

  p {{
    color: #475569;
    font-size: 14px;
    line-height: 1.5;
    margin: 0;
  }}
</style>
</head>

<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{message}</p>
    {form_html}
  </div>
</body>
</html>""",
        content_type="text/html",
    )


def _validate_unsubscribe_token(token):
    """
    Validate the unsubscribe token without performing any side effect.

    Returns:
        (contact, campaign_id, error)
    """

    try:
        payload = parse_unsubscribe_token(token)
    except signing.BadSignature:
        return (
            None,
            None,
            "This unsubscribe link is invalid or has expired.",
        )

    contact = Contact.objects.filter(
        id=payload.get("contact_id")
    ).first()

    if contact is None:
        return (
            None,
            None,
            "We couldn't find this subscriber — they may have already been removed.",
        )

    return contact, payload.get("campaign_id"), None


def _perform_unsubscribe(contact, campaign_id, source):
    """
    Perform the actual unsubscribe operation.

    This function is only called after an explicit POST confirmation
    or an RFC 8058 one-click unsubscribe POST.
    """

    contact.status = Contact.Status.UNSUBSCRIBED
    contact.save(update_fields=["status", "updated_at"])

    add_suppression(
        contact.email,
        "unsubscribed",
    )

    if campaign_id:
        from django.utils import timezone

        from analytics.models import CampaignEvent
        from campaigns.models import Campaign, CampaignRecipient

        campaign = Campaign.objects.filter(
            id=campaign_id
        ).first()

        if campaign is not None:
            recipient = CampaignRecipient.objects.filter(
                campaign=campaign,
                contact=contact,
            ).first()

            if recipient is not None:
                recipient.status = (
                    CampaignRecipient.Status.UNSUBSCRIBED
                )

                recipient.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

            CampaignEvent.objects.get_or_create(
                dedupe_key=(
                    f"self-serve-unsubscribe:"
                    f"{contact.id}:{campaign.id}"
                ),
                defaults={
                    "campaign": campaign,
                    "contact": contact,
                    "recipient": recipient,
                    "event_type": (
                        CampaignEvent.EventType.UNSUBSCRIBED
                    ),
                    "timestamp": timezone.now(),
                    "metadata": {
                        "source": source,
                    },
                },
            )


def _log_unsubscribe_link_viewed(
    contact,
    campaign_id,
    request,
):
    """
    Log an unsubscribe link view without unsubscribing.

    This allows analytics to distinguish between:
    - unsubscribe link views
    - confirmed unsubscribes
    - bot/scanner views
    """

    if not campaign_id:
        return

    try:
        from django.utils import timezone

        from analytics.models import CampaignEvent
        from campaigns.models import Campaign, CampaignRecipient
        from common.bot_detection import (
            client_ip_from_request,
            looks_like_bot,
        )

        campaign = Campaign.objects.filter(
            id=campaign_id
        ).first()

        if campaign is None:
            return

        recipient = CampaignRecipient.objects.filter(
            campaign=campaign,
            contact=contact,
        ).first()

        user_agent = request.META.get(
            "HTTP_USER_AGENT",
            "",
        )

        CampaignEvent.objects.create(
            campaign=campaign,
            contact=contact,
            recipient=recipient,
            event_type=(
                CampaignEvent.EventType.UNSUBSCRIBE_VIEWED
            ),
            timestamp=timezone.now(),
            metadata={
                "ip_address": client_ip_from_request(request),
                "user_agent": user_agent,
                "is_bot": looks_like_bot(user_agent),
            },
            dedupe_key=(
                f"unsubscribe-viewed:"
                f"{contact.id}:"
                f"{campaign.id}:"
                f"{timezone.now().timestamp()}"
            ),
        )

    except Exception:
        logger.exception(
            "Failed to log unsubscribe-link-viewed event "
            "for contact=%s",
            contact.id,
        )


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def unsubscribe_via_token(request, token):
    """
    GET /api/unsubscribe/<token>/

    Opening the unsubscribe link only displays a confirmation page.
    It does NOT unsubscribe the contact.

    POST /api/unsubscribe/<token>/

    Performs the actual unsubscribe.

    A POST can come from:
    1. The confirmation page.
    2. RFC 8058 one-click unsubscribe.
    """

    contact, campaign_id, error = _validate_unsubscribe_token(
        token
    )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------
    if request.method == "GET":

        if contact is not None:
            _log_unsubscribe_link_viewed(
                contact,
                campaign_id,
                request,
            )

        if error:
            return _unsubscribe_page(
                "Something went wrong",
                error,
                ok=False,
            )

        return _unsubscribe_page(
            "Unsubscribe from these emails?",
            (
                "Click below to confirm you no longer want "
                f"to receive emails at {contact.email}."
            ),
            confirm_form_token=token,
        )

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if error:
        if request.query_params.get("confirm"):
            return _unsubscribe_page(
                "Something went wrong",
                error,
                ok=False,
            )

        return Response(
            status=status.HTTP_400_BAD_REQUEST
        )

    is_confirm_page_submission = bool(
        request.query_params.get("confirm")
    )

    _perform_unsubscribe(
        contact,
        campaign_id,
        source=(
            "unsubscribe_page_confirmed"
            if is_confirm_page_submission
            else "one_click_post"
        ),
    )

    if is_confirm_page_submission:
        return _unsubscribe_page(
            "You've been unsubscribed",
            (
                f"{contact.email} will no longer receive "
                "emails from us. You can close this page."
            ),
        )

    # RFC 8058 one-click unsubscribe:
    # return a normal HTTP success response.
    return Response(
        status=status.HTTP_200_OK
    )
