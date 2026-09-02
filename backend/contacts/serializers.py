from rest_framework import serializers

from common.validators import is_valid_email

from .models import Contact, ContactList


class ContactListSerializer(serializers.ModelSerializer):
    contact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ContactList
        fields = ["id", "name", "description", "contact_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ContactSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    lists = serializers.PrimaryKeyRelatedField(many=True, queryset=ContactList.objects.none(), required=False)

    class Meta:
        model = Contact
        fields = [
            "id", "first_name", "last_name", "email", "phone", "status",
            "attributes", "lists", "full_name", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            self.fields["lists"].queryset = ContactList.objects.filter(owner=request.user)

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
