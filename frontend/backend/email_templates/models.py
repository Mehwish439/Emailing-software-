from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class EmailTemplate(TimeStampedModel):
    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    html_content = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_templates"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class TemplateImage(TimeStampedModel):
    """
    Images inserted into email templates via the "Insert image" -> "Upload
    from your computer" flow.

    Stored as raw bytes in the database (Supabase Postgres) rather than on
    local disk. Render's free-tier web service disk is ephemeral — anything
    written there is wiped on every redeploy or restart — so a local
    MEDIA_ROOT upload would silently disappear and break every email that
    already went out referencing it. The database is the one piece of
    storage in this architecture that's actually durable, so that's what
    backs this instead, avoiding the need for a separate paid file-storage
    service (S3, Cloudinary, etc.) just for this.

    Trade-off worth knowing: this isn't meant for large media libraries —
    see MAX_UPLOAD_SIZE_BYTES in views.py for the enforced per-image cap.
    For anything beyond occasional small images in campaign emails, a real
    object storage service would be the better fit.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="template_images"
    )
    content_type = models.CharField(max_length=100)
    data = models.BinaryField()
    original_filename = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_filename or f"image-{self.id}"