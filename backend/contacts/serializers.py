from rest_framework import serializers

from common.validators import is_valid_email

from .models import Contact, ContactList, Segment, Tag


class TagSerializer(serializers.ModelSerializer):
    contact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Tag
        fields = ["id", "name", "contact_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ContactListSerializer(serializers.ModelSerializer):
    contact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ContactList
        fields = ["id", "name", "description", "contact_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SegmentSerializer(serializers.ModelSerializer):
    contact_count = serializers.IntegerField(read_only=True)
    tags = serializers.PrimaryKeyRelatedField(many=True, queryset=Tag.objects.none(), required=False)
    lists = serializers.PrimaryKeyRelatedField(many=True, queryset=ContactList.objects.none(), required=False)

    class Meta:
        model = Segment
        fields = [
            "id", "name", "description", "tags", "lists", "status", "tag_match",
            "contact_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            self.fields["tags"].queryset = Tag.objects.filter(owner=request.user)
            self.fields["lists"].queryset = ContactList.objects.filter(owner=request.user)

    def validate(self, attrs):
        if not (attrs.get("tags") or attrs.get("lists") or attrs.get("status")):
            raise serializers.ValidationError(
                "A segment needs at least one criterion (a tag, a list, or a status) — otherwise it would match every contact."
            )
        return attrs


class ContactSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    lists = serializers.PrimaryKeyRelatedField(many=True, queryset=ContactList.objects.none(), required=False)
    tags = serializers.PrimaryKeyRelatedField(many=True, queryset=Tag.objects.none(), required=False)

    class Meta:
        model = Contact
        fields = [
            "id", "first_name", "last_name", "email", "phone", "status",
            "attributes", "lists", "tags", "full_name", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            self.fields["lists"].queryset = ContactList.objects.filter(owner=request.user)
            self.fields["tags"].queryset = Tag.objects.filter(owner=request.user)

    def validate_email(self, value):
        if not is_valid_email(value):
            raise serializers.ValidationError("Enter a valid email address.")
        request = self.context.get("request")
        qs = Contact.objects.filter(owner=request.user, email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A contact with this email already exists.")
        return value.lower()


class BulkDeleteSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class ListMembershipSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class CSVImportResultSerializer(serializers.Serializer):
    imported = serializers.IntegerField()
    duplicates = serializers.IntegerField()
    invalid = serializers.IntegerField()
    total_processed = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField(), required=False)
