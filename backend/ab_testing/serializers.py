# NEW FILE (A/B testing feature)
from rest_framework import serializers

from .models import CampaignVariant


class CampaignVariantSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True)

    class Meta:
        model = CampaignVariant
        fields = [
            "id", "campaign", "label", "subject", "template", "template_name",
            "split_percentage", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "campaign", "created_at", "updated_at"]


class VariantInputSerializer(serializers.Serializer):
    """
    Input shape for one variant when creating/replacing a campaign's A/B
    variants (see the PUT branch of ab_testing/views.py::campaign_variants).
    Deliberately a plain Serializer (not a ModelSerializer bound to the
    campaign) since `template` here is validated for real -- including
    ownership -- in ab_testing.services.set_campaign_variants, which is
    also the single place campaign.subject/template get kept in sync with
    Version A. Keeping that logic in one place (not split between here and
    services.py) avoids the two drifting out of sync.
    """

    label = serializers.ChoiceField(choices=CampaignVariant.Label.choices)
    subject = serializers.CharField(max_length=255, allow_blank=False)
    template = serializers.IntegerField()
    split_percentage = serializers.IntegerField(min_value=1, max_value=99)


class SetCampaignVariantsSerializer(serializers.Serializer):
    variants = VariantInputSerializer(many=True)
