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
from .services import STANDARD_MERGE_FIELDS, CSVImportError, import_contacts_from_csv
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

    @action(detail=False, methods=["get"], url_path="merge-fields")
    def merge_fields(self, request):
        """
        GET /api/contacts/merge-fields/

        Returns every template variable available for this user's contacts:
        the standard Contact fields plus every column preserved from
        CSV/Excel imports (Contact.attributes — see services.py). Powers the
        "Insert Variable" dropdown in the template editor.
        """
        fields = list(STANDARD_MERGE_FIELDS)
        seen = set(fields)

        attributes_by_contact = Contact.objects.filter(owner=request.user).exclude(
            attributes={}
        ).values_list("attributes", flat=True)
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


def _unsubscribe_page(title, message, ok=True, confirm_form_token=None):
    """
    confirm_form_token: when given, renders a real HTML <form> whose submit
    button POSTs back to this same URL to actually confirm the unsubscribe.
    This is the key safety property: an automated GET (a security scanner
    prefetching/scanning the link, a link-preview bot, etc.) only ever
    renders this page — it never submits the form, since that requires an
    actual click from a real browser session. Nothing is unsubscribed until
    that POST happens.
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
</form>"""
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
<body><div class="card"><h1>{title}</h1><p>{message}</p>{form_html}</div></body></html>""",
        content_type="text/html",
    )


def _validate_unsubscribe_token(token):
    """
    Parses and validates the token WITHOUT any side effect — used by the GET
    path so merely opening/scanning the link can never itself change
    anything. Returns (contact_or_none, campaign_id_or_none, error_or_none).
    """
    try:
        payload = parse_unsubscribe_token(token)
    except signing.BadSignature:
        return None, None, "This unsubscribe link is invalid or has expired."

    contact = Contact.objects.filter(id=payload.get("contact_id")).first()
    if contact is None:
        return None, None, "We couldn't find this subscriber — they may have already been removed."

    return contact, payload.get("campaign_id"), None


def _perform_unsubscribe(contact, campaign_id, source):
    """
    The actual side-effecting action — only ever called once a human has
    explicitly confirmed (via the confirmation page's form POST) or a
    mailbox provider has sent the explicit RFC 8058 one-click POST. Never
    called from a bare GET.
    """
    contact.status = Contact.Status.UNSUBSCRIBED
    contact.save(update_fields=["status", "updated_at"])
    add_suppression(contact.email, "unsubscribed")

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
                    "metadata": {"source": source},
                },
            )


def _log_unsubscribe_link_viewed(contact, campaign_id, request):
    """
    Logs that the unsubscribe link was opened (GET) — WITHOUT unsubscribing
    anyone. This is what lets analytics show "43 unsubscribe link views" as
    a distinct, honest number from "confirmed unsubscribes", and lets you
    see how many of those views came from a detected bot/scanner.
    Best-effort: a logging failure must never block showing the page.
    """
    if not campaign_id:
        return
    try:
        from django.utils import timezone

        from analytics.models import CampaignEvent
        from campaigns.models import Campaign, CampaignRecipient
        from common.bot_detection import client_ip_from_request, looks_like_bot

        campaign = Campaign.objects.filter(id=campaign_id).first()
        if campaign is None:
            return
        recipient = CampaignRecipient.objects.filter(campaign=campaign, contact=contact).first()
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        CampaignEvent.objects.create(
            campaign=campaign,
            contact=contact,
            recipient=recipient,
            event_type=CampaignEvent.EventType.UNSUBSCRIBE_VIEWED,
            timestamp=timezone.now(),
            metadata={
                "ip_address": client_ip_from_request(request),
                "user_agent": user_agent,
                "is_bot": looks_like_bot(user_agent),
            },
            dedupe_key=f"unsubscribe-viewed:{contact.id}:{campaign.id}:{timezone.now().timestamp()}",
        )
    except Exception:  # noqa: BLE001 — logging a view must never break the page
        logger.exception("Failed to log unsubscribe-link-viewed event for contact=%s", contact.id)


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def unsubscribe_via_token(request, token):
    """
    GET  /api/unsubscribe/<token>/  -- opening the link (a human, OR a
                                        security scanner/link-preview bot
                                        prefetching it) — shows a
                                        confirmation page ONLY. Does NOT
                                        unsubscribe anyone by itself; see
                                        the module-level note above about
                                        why an unconditional GET-unsubscribe
                                        is unsafe.
    POST /api/unsubscribe/<token>/  -- actually unsubscribes. Reached either
                                        by RFC 8058's List-Unsubscribe-Post
                                        (sent automatically by mailbox
                                        providers ONLY when a human clicks
                                        their own client's "Unsubscribe"
                                        button — that's the whole point of
                                        the spec, so this one is safe to
                                        auto-confirm) or by a human
                                        submitting the confirmation page's
                                        form above (marked with ?confirm=1
                                        so we know to render the HTML result
                                        page rather than a bare status code).

    No authentication — the signed token itself is the credential, and it
    only ever grants unsubscribing the one (contact, campaign) it was minted
    for (see contacts/unsubscribe.py).
    """
    contact, campaign_id, error = _validate_unsubscribe_token(token)

    if request.method == "GET":
        if contact is not None:
            _log_unsubscribe_link_viewed(contact, campaign_id, request)
        if error:
            return _unsubscribe_page("Something went wrong", error, ok=False)
        return _unsubscribe_page(
            "Unsubscribe from these emails?",
            f"Click below to confirm you no longer want to receive emails at {contact.email}.",
            confirm_form_token=token,
        )

    # POST from here on.
    if error:
        if request.query_params.get("confirm"):
            return _unsubscribe_page("Something went wrong", error, ok=False)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    is_confirm_page_submission = bool(request.query_params.get("confirm"))
    _perform_unsubscribe(
        contact, campaign_id, source="unsubscribe_page_confirmed" if is_confirm_page_submission else "one_click_post"
    )

    if is_confirm_page_submission:
        return _unsubscribe_page(
            "You've been unsubscribed",
            f"{contact.email} will no longer receive emails from us. You can close this page.",
        )
    # RFC 8058 one-click unsubscribe via mailbox provider: no page is shown,
    # just a plain success status is expected.
    return Response(status=status.HTTP_200_OK)




if error:
    if request.query_params.get("confirm"):
        return _unsubcribe_page("Something went wrong",error,ok=False)
    return Response(status=status.HTTP_400_BAD_REQUEST)
is_confirm_page_submission = bool(request.query_params.get("confirm"))
_perform_unsubscribe(
    contact, campaign_id, source="unsubscribe_page_confirmed" if is_confirm_page_submission else "one_click_post"
)


if error: 
    if request.query_params.get("confirm"):
        return _unsubscribe_page("Something went wrong",error,ok=False)
    return Response(status=status.HTTP_400_BAD_REQUEST)
is_confirm_page_submission = bool(request.query_params.get("confirm"))
_perform_unsubscribe(
    contact, campaign_id,source="unsubscribe_page_confirmed" i
)

if error:
    if request.query_params.get("confirm"):
        return _unsubscribe_page("something went wrong", error, ok=False)
    return Response (status=status.HTTP_400_BAD_REQUEST)
is_confirm_page_submission = bool (request.query_params.get("confirm"))
_perform_unsubscribe(
    contact, campaign_id,source="unsubscribe_page_confirmed"i
)