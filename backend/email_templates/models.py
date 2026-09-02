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
