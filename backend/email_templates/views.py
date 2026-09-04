from django.http import HttpResponse
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import EmailTemplate, TemplateImage
from .serializers import EmailTemplateSerializer
from .starter_templates import STARTER_TEMPLATES

# Kept intentionally small: images are stored as bytes in Postgres (see
# TemplateImage's docstring), so the cap here isn't just about upload
# sanity — it directly bounds how much database storage this feature can
# consume. 3MB comfortably covers a logo or a banner image without being
# generous enough to turn this into a media library.
MAX_UPLOAD_SIZE_BYTES = 3 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class EmailTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = EmailTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "subject"]
    ordering_fields = ["created_at", "name"]

    def get_queryset(self):
        return EmailTemplate.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        from contacts.models import Contact

        from .rendering import render_template_for_contact

        template = self.get_object()
        # A template isn't tied to any particular campaign/contact list, so
        # fall back to any one of this user's own contacts (if they have
        # one) to show real {{variable}} values here too.
        sample_contact = Contact.objects.filter(owner=request.user).first()
        if sample_contact is not None:
            subject, html_content = render_template_for_contact(
                template.subject, template.html_content, sample_contact, extra_fields={"unsubscribe_url": "#"}
            )
        else:
            subject, html_content = template.subject, template.html_content
        return Response({"subject": subject, "html_content": html_content})

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        template = self.get_object()
        clone = EmailTemplate.objects.create(
            name=f"{template.name} (Copy)",
            subject=template.subject,
            html_content=template.html_content,
            created_by=request.user,
        )
        return Response(EmailTemplateSerializer(clone).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_starter_templates(request):
    """
    GET /api/templates/starters/

    Read-only library of pre-built starter templates (see
    email_templates/starter_templates.py) that the "start from a template"
    gallery in the frontend's template editor fetches from when creating a
    new template. Picking one just pre-fills the editor's fields — nothing
    is saved until the user actually hits Save, same as starting blank.
    """
    return Response(STARTER_TEMPLATES)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def upload_template_image(request):
    """
    POST /api/templates/images/  (multipart/form-data, field name "file")

    Uploads an image to embed in an email template's HTML content and
    returns a public URL for it (usable directly in an <img src="..."> tag
    or via the template editor's "Insert image" -> "Upload from your
    computer" flow). Requires login to upload; the returned URL itself is
    publicly fetchable with no auth, since recipients' email clients (not
    our frontend) are what actually load it.
    """
    file_obj = request.FILES.get("file")
    if not file_obj:
        return Response({"detail": "No file uploaded. Send it as multipart form field 'file'."}, status=400)

    if file_obj.content_type not in ALLOWED_CONTENT_TYPES:
        return Response(
            {"detail": f"Unsupported image type '{file_obj.content_type}'. Allowed: PNG, JPEG, GIF, WebP."},
            status=400,
        )

    if file_obj.size > MAX_UPLOAD_SIZE_BYTES:
        return Response(
            {"detail": f"Image is too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB."},
            status=400,
        )

    image = TemplateImage.objects.create(
        owner=request.user,
        content_type=file_obj.content_type,
        data=file_obj.read(),
        original_filename=file_obj.name[:255],
        size_bytes=file_obj.size,
    )

    from django.conf import settings

    url = f"{settings.BACKEND_BASE_URL}/api/templates/images/{image.id}/content/"
    return Response({"id": image.id, "url": url}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
def template_image_content(request, pk):
    """
    GET /api/templates/images/<id>/content/

    Serves the raw image bytes for a previously uploaded template image.
    Public/unauthenticated on purpose — this URL is what actually appears
    inside sent campaign emails, fetched directly by recipients' email
    clients, which obviously can't send our JWT.
    """
    image = TemplateImage.objects.filter(id=pk).first()
    if image is None:
        return HttpResponse(status=404)

    response = HttpResponse(bytes(image.data), content_type=image.content_type)
    # Images don't change once uploaded — safe to cache aggressively both in
    # the browser/email client and any intermediate proxy/CDN.
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response