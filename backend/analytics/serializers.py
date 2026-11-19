from rest_framework import serializers

from campaigns.models import CampaignRecipient


class AllCampaignsRecipientSerializer(serializers.ModelSerializer):
    """
    Same shape as campaigns.serializers.CampaignRecipientSerializer, plus
    campaign_id/campaign_name — used by the cross-campaign recipients
    endpoint (GET /api/analytics/recipients/) so the frontend can show
    which campaign each row belongs to when recipients are listed across
    ALL of a user's campaigns (the Dashboard and "All campaigns" view on
    Analytics), rather than just one campaign's own detail page.
    """

    contact_email = serializers.EmailField(source="contact.email", read_only=True)
    contact_name = serializers.CharField(source="contact.full_name", read_only=True)
    campaign_id = serializers.IntegerField(source="campaign.id", read_only=True)
    campaign_name = serializers.CharField(source="campaign.name", read_only=True)

    class Meta:
        model = CampaignRecipient
        fields = [
            "id",
            "contact",
            "contact_email",
            "contact_name",
            "campaign_id",
            "campaign_name",
            "status",
            "sent_at",
        ]
        read_only_fields = fields
