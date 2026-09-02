from rest_framework import serializers

from campaigns.models import Campaign

from .models import ScheduledCampaign


class ScheduledCampaignSerializer(serializers.ModelSerializer):
    campaign_name = serializers.CharField(source="campaign.name", read_only=True)

    class Meta:
        model = ScheduledCampaign
        fields = [
            "id", "campaign", "campaign_name", "scheduled_at", "timezone", "status",
            "started_at", "completed_at", "cancelled_at", "error_message", "created_at",
        ]
        read_only_fields = ["id", "status", "started_at", "completed_at", "cancelled_at", "error_message", "created_at"]


class CreateScheduleSerializer(serializers.Serializer):
    campaign = serializers.PrimaryKeyRelatedField(queryset=Campaign.objects.none())
    scheduled_at = serializers.DateTimeField()
    timezone = serializers.CharField(default="Asia/Karachi")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            self.fields["campaign"].queryset = Campaign.objects.filter(created_by=request.user)


class UpdateScheduleSerializer(serializers.Serializer):
    scheduled_at = serializers.DateTimeField(required=False)
    timezone = serializers.CharField(required=False)
