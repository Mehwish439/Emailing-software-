from django.db import transaction
from rest_framework import serializers

from contacts.models import ContactList, Segment, Tag
from email_templates.models import EmailTemplate
from scheduling.services import validate_timezone
from signup_forms.models import SignupForm

from common.exceptions import ValidationAppError

from .models import Automation, AutomationEnrollment, AutomationExecution, AutomationStep


class OwnedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """PK field limited to the requesting user's own rows (no cross-account attaching)."""

    def __init__(self, model, owner_field="owner", **kwargs):
        self._model = model
        self._owner_field = owner_field
        super().__init__(queryset=model.objects.all(), **kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            return self._model.objects.filter(**{self._owner_field: request.user})
        return self._model.objects.none()


def _user(serializer):
    return serializer.context["request"].user


class AutomationStepSerializer(serializers.ModelSerializer):
    email_template = OwnedPrimaryKeyField(EmailTemplate, owner_field="created_by", required=False, allow_null=True)
    email_template_name = serializers.CharField(source="email_template.name", read_only=True, default=None)

    class Meta:
        model = AutomationStep
        fields = [
            "id", "step_order", "action_type", "email_template", "email_template_name",
            "delay_value", "delay_unit", "configuration",
        ]
        read_only_fields = ["id", "step_order"]

    def validate_configuration(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("configuration must be an object.")
        condition = value.get("condition")
        if condition:
            user = _user(self)
            ctype = condition.get("type")
            lookups = {
                "has_tag": (Tag, "tag_id"), "in_list": (ContactList, "list_id"), "in_segment": (Segment, "segment_id"),
            }
            if ctype not in lookups:
                raise serializers.ValidationError("Unsupported condition type.")
            model, key = lookups[ctype]
            if not model.objects.filter(id=condition.get(key), owner=user).exists():
                raise serializers.ValidationError(f"Condition {key} not found in your account.")
        return value

    def validate(self, attrs):
        action = attrs.get("action_type", AutomationStep.ActionType.SEND_EMAIL)
        if action == AutomationStep.ActionType.SEND_EMAIL and not attrs.get("email_template"):
            raise serializers.ValidationError({"email_template": "Choose a template for a Send Email step."})
        if action == AutomationStep.ActionType.WAIT and not attrs.get("delay_value"):
            raise serializers.ValidationError({"delay_value": "A Wait step needs a delay greater than 0."})
        if action != AutomationStep.ActionType.SEND_EMAIL:
            attrs["email_template"] = None
        return attrs


class AutomationSerializer(serializers.ModelSerializer):
    steps = AutomationStepSerializer(many=True, required=False)
    status = serializers.CharField(read_only=True)
    # Annotated by the viewset for the list page (see views.AutomationViewSet.get_queryset).
    enrolled_count = serializers.IntegerField(read_only=True, default=0)
    active_count = serializers.IntegerField(read_only=True, default=0)
    emails_sent = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Automation
        fields = [
            "id", "name", "description", "trigger_type", "trigger_config", "status",
            "sender_name", "sender_email", "timezone", "allow_reenrollment", "steps",
            "enrolled_count", "active_count", "emails_sent", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

    # -- validation ---------------------------------------------------------
    def validate_timezone(self, value):
        try:
            validate_timezone(value)  # same helper the campaign scheduler uses
        except ValidationAppError as exc:
            raise serializers.ValidationError(str(exc))
        return value

    def validate_name(self, value):
        qs = Automation.objects.filter(owner=_user(self), name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You already have an automation with this name.")
        return value

    def validate(self, attrs):
        trigger_type = attrs.get("trigger_type", getattr(self.instance, "trigger_type", None))
        config = attrs.get("trigger_config", getattr(self.instance, "trigger_config", None)) or {}
        user = _user(self)

        if trigger_type == Automation.TriggerType.SIGNUP_FORM_SUBMITTED:
            fid = config.get("signup_form_id")
            if fid and not SignupForm.objects.filter(id=fid, owner=user).exists():
                raise serializers.ValidationError({"trigger_config": "Signup form not found in your account."})
            config = {"signup_form_id": fid} if fid else {}
        elif trigger_type == Automation.TriggerType.CONTACT_ADDED:
            lid = config.get("list_id")
            if lid and not ContactList.objects.filter(id=lid, owner=user).exists():
                raise serializers.ValidationError({"trigger_config": "List not found in your account."})
            config = {"list_id": lid} if lid else {}
        else:
            config = {}
        if "trigger_config" in attrs or "trigger_type" in attrs:
            attrs["trigger_config"] = config

        if self.instance and self.instance.status == Automation.Status.ACTIVE:
            changed_trigger = ("trigger_type" in attrs and attrs["trigger_type"] != self.instance.trigger_type) or (
                "trigger_config" in attrs and attrs["trigger_config"] != self.instance.trigger_config
            )
            if "steps" in attrs or changed_trigger:
                raise serializers.ValidationError(
                    {"detail": "Pause the automation before changing its trigger or steps."}
                )
        return attrs

    # -- writes --------------------------------------------------------------
    @staticmethod
    def _replace_steps(automation, steps_data):
        automation.steps.all().delete()
        AutomationStep.objects.bulk_create([
            AutomationStep(automation=automation, step_order=i, **data) for i, data in enumerate(steps_data, start=1)
        ])

    @transaction.atomic
    def create(self, validated_data):
        steps_data = validated_data.pop("steps", [])
        automation = Automation.objects.create(owner=_user(self), **validated_data)
        self._replace_steps(automation, steps_data)
        return automation

    @transaction.atomic
    def update(self, instance, validated_data):
        steps_data = validated_data.pop("steps", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if steps_data is not None:
            self._replace_steps(instance, steps_data)
        return instance


class AutomationEnrollmentSerializer(serializers.ModelSerializer):
    contact_email = serializers.CharField(source="contact.email", read_only=True)
    contact_name = serializers.CharField(source="contact.full_name", read_only=True)

    class Meta:
        model = AutomationEnrollment
        fields = [
            "id", "contact", "contact_email", "contact_name", "status", "current_step_order", "started_at",
            "next_run_at", "completed_at", "last_error", "source",
        ]


class AutomationExecutionSerializer(serializers.ModelSerializer):
    contact_email = serializers.CharField(source="contact.email", read_only=True)
    template_name = serializers.SerializerMethodField()

    class Meta:
        model = AutomationExecution
        fields = [
            "id", "enrollment", "contact", "contact_email", "step_order", "action_type", "template_name", "status",
            "attempt", "executed_at", "error_message", "provider_message_id", "delivered_at", "opened_at",
            "clicked_at", "created_at",
        ]

    def get_template_name(self, obj):
        return (obj.metadata or {}).get("template_name") or None


class EnrollRequestSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField(required=False)
    contact_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=False)

    def validate(self, attrs):
        ids = list(attrs.get("contact_ids") or [])
        if attrs.get("contact_id") is not None:
            ids.append(attrs["contact_id"])
        if not ids:
            raise serializers.ValidationError("Provide contact_id or contact_ids.")
        attrs["all_ids"] = list(dict.fromkeys(ids))
        return attrs


class ExternalEventSerializer(serializers.Serializer):
    event = serializers.CharField()
    email = serializers.EmailField(required=False)
    contact_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if attrs.get("email") is None and attrs.get("contact_id") is None:
            raise serializers.ValidationError("Provide email or contact_id.")
        return attrs
