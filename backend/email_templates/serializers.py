from rest_framework import serializers

from .models import EmailTemplate


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ["id", "name", "subject", "html_content", "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_html_content(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Template content cannot be empty.")
        return value
