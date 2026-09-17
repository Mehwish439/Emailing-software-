# NEW FILE (Signup Forms feature)
from rest_framework import serializers

from contacts.models import ContactList, Tag
from contacts.serializers import scope_many_related_queryset

from .models import SignupForm


def build_embed_snippet(form, request):
    """
    Builds the copy-pasteable embed snippet for a form's management page
    (see FINAL RESPONSE's "Embed Code" section). The API/script origin is
    derived from the incoming request (request.build_absolute_uri) rather
    than a hardcoded/settings URL, matching how email_templates/views.py's
    uploaded-image URLs are already built in this codebase — so it's
    correct in local dev, staging, and production without extra config.
    """
    script_src = request.build_absolute_uri("/api/public/signup-forms/embed.js")
    target_id = f"qrm-signup-form-{form.public_id}"
    return (
        f'<div id="{target_id}"></div>\n'
        f'<script src="{script_src}" '
        f'data-form-id="{form.public_id}" data-target="{target_id}" async></script>'
    )


class SignupFormSerializer(serializers.ModelSerializer):
    """
    Management serializer — used by the authenticated CRUD endpoints only.
    Never used for the public form-detail/submission endpoints (see
    PublicSignupFormSerializer), so it's fine for this to include
    everything, including which list/tags a submission feeds into.
    """

    tags = serializers.PrimaryKeyRelatedField(many=True, queryset=Tag.objects.none(), required=False)
    contact_list = serializers.PrimaryKeyRelatedField(
        queryset=ContactList.objects.none(), required=False, allow_null=True
    )
    contact_list_name = serializers.CharField(source="contact_list.name", read_only=True, default=None)
    embed_code = serializers.SerializerMethodField()
    public_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = SignupForm
        fields = [
            "id",
            "public_id",
            "name",
            "description",
            "contact_list",
            "contact_list_name",
            "tags",
            "collect_first_name",
            "collect_last_name",
            "button_text",
            "success_message",
            "is_active",
            "submission_count",
            "embed_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "submission_count", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            scope_many_related_queryset(self.fields["tags"], Tag.objects.filter(owner=request.user))
            scope_many_related_queryset(
                self.fields["contact_list"], ContactList.objects.filter(owner=request.user)
            )

    def get_embed_code(self, obj):
        request = self.context.get("request")
        if request is None or obj.pk is None:
            return None
        return build_embed_snippet(obj, request)

    def validate(self, attrs):
        # A submission has to attach the new contact to *something* —
        # otherwise it's just silently discarded data (worse than the
        # duplicate-contact concerns the spec calls out under section 3).
        contact_list = attrs.get("contact_list", getattr(self.instance, "contact_list", None))
        tags = attrs.get("tags", list(self.instance.tags.all()) if self.instance else [])
        if not contact_list and not tags:
            raise serializers.ValidationError(
                "Select at least a list or a tag for this form's submissions to be added to."
            )
        return attrs

    def validate_button_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Button text cannot be blank.")
        return value

    def validate_success_message(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Success message cannot be blank.")
        return value


class PublicSignupFormSerializer(serializers.ModelSerializer):
    """
    What an anonymous visitor's browser is allowed to see when the embed
    script fetches a form's details. Deliberately excludes contact_list,
    tags, owner, submission_count, and every other management-only field —
    see signup_forms/views.py's SECURITY note.
    """

    class Meta:
        model = SignupForm
        fields = ["public_id", "name", "description", "collect_first_name", "collect_last_name", "button_text"]


class SignupFormSubmitSerializer(serializers.Serializer):
    """
    Validates an anonymous visitor's submission. `hp_field` is an
    invisible-to-humans honeypot input the embed script renders (see
    embed.py) — a real visitor's browser never fills it in, so any
    non-empty value here is a strong spam signal (see views.py).
    """

    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    hp_field = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        return value.strip().lower()
