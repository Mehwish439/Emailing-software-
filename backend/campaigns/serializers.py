from rest_framework import serializers

from contacts.models import ContactList
from email_templates.models import EmailTemplate

from .models import Campaign, CampaignRecipient


class CampaignRecipientSerializer(serializers.ModelSerializer):
    contact_email = serializers.EmailField(source="contact.email", read_only=True)
    contact_name = serializers.CharField(source="contact.full_name", read_only=True)

    class Meta:
        model = CampaignRecipient
        fields = ["id", "contact", "contact_email", "contact_name", "status", "sent_at"]
        read_only_fields = fields


class CampaignSerializer(serializers.ModelSerializer):
    recipient_count = serializers.IntegerField(read_only=True)
    template_name = serializers.CharField(source="template.name", read_only=True)
    eligible_recipient_count = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            "id", "name", "subject", "sender_name", "sender_email", "template", "template_name",
            "contact_lists", "status", "brevo_campaign_id", "recipient_count", "eligible_recipient_count",
            "created_by", "created_at", "updated_at", "sent_at", "failure_reason",
        ]
        read_only_fields = ["id", "status", "brevo_campaign_id", "created_by", "created_at", "updated_at", "sent_at", "failure_reason"]

    def get_eligible_recipient_count(self, obj):
        """
        A live preview of how many contacts would actually be sent to right
        now — computed from the campaign's selected lists, filtered to active
        and non-suppressed contacts — the same logic send_campaign_now() uses
        to build the real recipient snapshot. Unlike recipient_count (which
        only reflects CampaignRecipient rows that already exist, i.e. only
        after a send has been attempted), this updates live as contact_lists
        changes, so it's what to check *before* sending to confirm the list
        selection actually has eligible contacts in it.
        """
        if not obj.pk:
            return 0
        return obj.eligible_contacts_queryset().count()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            self.fields["template"].queryset = EmailTemplate.objects.filter(created_by=request.user)
            self.fields["contact_lists"].queryset = ContactList.objects.filter(owner=request.user)

    def validate(self, attrs):
        # On update, only draft campaigns may be freely edited.
        if self.instance and self.instance.status not in (Campaign.Status.DRAFT,):
            raise serializers.ValidationError(
                "Only draft campaigns can be edited. Cancel the schedule first if needed."
            )
        return attrs


class SendTestEmailSerializer(serializers.Serializer):
    test_email = serializers.EmailField()


class CampaignAnalyticsSerializer(serializers.Serializer):
    campaign_id = serializers.IntegerField()
    campaign_name = serializers.CharField()
    sent = serializers.IntegerField()
    delivered = serializers.IntegerField()
    opened = serializers.IntegerField()
    clicked = serializers.IntegerField()
    soft_bounced = serializers.IntegerField()
    hard_bounced = serializers.IntegerField()
    blocked = serializers.IntegerField()
    spam = serializers.IntegerField()
    unsubscribed = serializers.IntegerField()
    delivery_rate = serializers.FloatField()
    open_rate = serializers.FloatField()
    click_rate = serializers.FloatField()
    bounce_rate = serializers.FloatField()
    unsubscribe_rate = serializers.FloatField()
    spam_rate = serializers.FloatField()