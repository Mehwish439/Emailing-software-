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
from .services import CSVImportError, import_contacts_from_csv
from .services_suppression import add_suppression
from .unsubscribe import parse_unsubscribe_token


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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "lists"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    ordering_fields = ["created_at", "email", "first_name", "last_name"]

    def get_queryset(self):
        return Contact.objects.filter(owner=self.request.user).prefetch_related("lists")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deleted_count, _ = Contact.objects.filter(
            owner=request.user, id__in=serializer.validated_data["ids"]
        ).delete()
        return Response({"deleted": deleted_count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="import-csv")
    def import_csv(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "A CSV file must be uploaded under the 'file' field."}, status=400)
        list_ids = request.data.getlist("list_ids") if hasattr(request.data, "getlist") else request.data.get("list_ids", [])
        try:
            result = import_contacts_from_csv(request.user, file_obj, list_ids=list_ids)
        except CSVImportError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(CSVImportResultSerializer(result).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="add-to-list")
    def add_to_list(self, request):
        list_id = request.data.get("list_id")
        contact_list = ContactList.objects.filter(owner=request.user, id=list_id).first()
        if not contact_list:
            return Response({"detail": "Contact list not found."}, status=404)
        serializer = ListMembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contacts = Contact.objects.filter(owner=request.user, id__in=serializer.validated_data["contact_ids"])
        for contact in contacts:
            contact.lists.add(contact_list)
        return Response({"added": contacts.count(), "list": contact_list.id})

    @action(detail=False, methods=["post"], url_path="remove-from-list")
    def remove_from_list(self, request):
        list_id = request.data.get("list_id")
        contact_list = ContactList.objects.filter(owner=request.user, id=list_id).first()
        if not contact_list:
            return Response({"detail": "Contact list not found."}, status=404)
        serializer = ListMembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contacts = Contact.objects.filter(owner=request.user, id__in=serializer.validated_data["contact_ids"])
        for contact in contacts:
            contact.lists.remove(contact_list)
        return Response({"removed": contacts.count(), "list": contact_list.id})


def _unsubscribe_page(title, message, ok=True):
    color = "#059669" if ok else "#dc2626"
    return HttpResponse(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #f8fafc;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #fff; border-radius: 12px; padding: 40px; max-width: 420px; text-align: center;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  h1 {{ color: {color}; font-size: 20px; margin: 0 0 12px; }}
  p {{ color: #475569; font-size: 14px; line-height: 1.5; margin: 0; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>""",
        content_type="text/html",
    )


def _process_unsubscribe(token):
    """
    Shared logic for the GET (human clicks the link) and POST (RFC 8058
    one-click List-Unsubscribe-Post, sent automatically by mailbox providers
    without a page ever being rendered) unsubscribe paths.
    Returns (contact_or_none, error_message_or_none).
    """
    try:
        payload = parse_unsubscribe_token(token)
    except signing.BadSignature:
        return None, "This unsubscribe link is invalid or has expired."

    contact = Contact.objects.filter(id=payload.get("contact_id")).first()
    if contact is None:
        return None, "We couldn't find this subscriber — they may have already been removed."

    contact.status = Contact.Status.UNSUBSCRIBED
    contact.save(update_fields=["status", "updated_at"])
    add_suppression(contact.email, "unsubscribed")

    campaign_id = payload.get("campaign_id")
    if campaign_id:
        # Mirrors what an "unsubscribed" webhook event does, so self-serve
        # unsubscribes show up in campaign analytics too — useful in local
        # dev especially, since Brevo's webhook can't reach localhost.
        from django.utils import timezone

        from analytics.models import CampaignEvent
        from campaigns.models import Campaign, CampaignRecipient

        campaign = Campaign.objects.filter(id=campaign_id).first()
        if campaign is not None:
            recipient = CampaignRecipient.objects.filter(campaign=campaign, contact=contact).first()
            if recipient is not None:
                recipient.status = CampaignRecipient.Status.UNSUBSCRIBED
                recipient.save(update_fields=["status", "updated_at"])
            CampaignEvent.objects.get_or_create(
                dedupe_key=f"self-serve-unsubscribe:{contact.id}:{campaign.id}",
                defaults={
                    "campaign": campaign,
                    "contact": contact,
                    "recipient": recipient,
                    "event_type": CampaignEvent.EventType.UNSUBSCRIBED,
                    "timestamp": timezone.now(),
                    "metadata": {"source": "self-serve-unsubscribe-link"},
                },
            )

    return contact, None


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def unsubscribe_via_token(request, token):
    """
    GET  /api/unsubscribe/<token>/  -- the link a human clicks inside the email body
    POST /api/unsubscribe/<token>/  -- RFC 8058 one-click unsubscribe, triggered
                                        automatically by mailbox providers (Gmail,
                                        etc.) from the List-Unsubscribe-Post header,
                                        with no page ever shown to the user

    No authentication — the signed token itself is the credential, and it
    only ever grants unsubscribing the one (contact, campaign) it was minted
    for (see contacts/unsubscribe.py).
    """
    contact, error = _process_unsubscribe(token)

    if request.method == "POST":
        # One-click unsubscribe via mailbox provider: no page is shown, just
        # a plain success/failure response is expected.
        return Response(status=status.HTTP_200_OK if contact else status.HTTP_400_BAD_REQUEST)

    if error:
        return _unsubscribe_page("Something went wrong", error, ok=False)
    return _unsubscribe_page(
        "You've been unsubscribed",
        f"{contact.email} will no longer receive emails from us. You can close this page.",
    )