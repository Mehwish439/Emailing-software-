# NEW FILE (A/B testing feature)
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate

from .models import CampaignVariant

User = get_user_model()


class ABTestingTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.template_a = EmailTemplate.objects.create(
            name="Version A Template", subject="A", html_content="<p>Hello A</p>", created_by=self.user
        )
        self.template_b = EmailTemplate.objects.create(
            name="Version B Template", subject="B", html_content="<p>Hello B</p>", created_by=self.user
        )
        self.contact_list = ContactList.objects.create(owner=self.user, name="Main")
        # 10 contacts so a 50/50 (and a 30/70) split has room to actually differ.
        self.contacts = [
            Contact.objects.create(owner=self.user, email=f"contact{i}@example.com") for i in range(10)
        ]
        for contact in self.contacts:
            contact.lists.add(self.contact_list)

    def _create_ab_campaign(self):
        url = reverse("campaign-list")
        payload = {
            "name": "Subject Line Test",
            "subject": "placeholder",  # overwritten from Version A once variants are set
            "sender_name": "Me",
            "sender_email": "me@example.com",
            "template": self.template_a.id,
            "contact_lists": [self.contact_list.id],
            "campaign_type": Campaign.CampaignType.AB_TEST,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return Campaign.objects.get(id=response.data["id"])

    def _set_variants(self, campaign, split_a=50, split_b=50):
        url = reverse("campaign-ab-variants", args=[campaign.id])
        payload = {
            "variants": [
                {"label": "A", "subject": "Subject A", "template": self.template_a.id, "split_percentage": split_a},
                {"label": "B", "subject": "Subject B", "template": self.template_b.id, "split_percentage": split_b},
            ]
        }
        return self.client.put(url, payload, format="json")

    # -- Variant configuration -------------------------------------------------

    def test_set_variants_success_and_mirrors_version_a_onto_campaign(self):
        campaign = self._create_ab_campaign()
        response = self._set_variants(campaign)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(CampaignVariant.objects.filter(campaign=campaign).count(), 2)

        campaign.refresh_from_db()
        self.assertEqual(campaign.subject, "Subject A")
        self.assertEqual(campaign.template_id, self.template_a.id)

    def test_set_variants_rejects_split_not_summing_to_100(self):
        campaign = self._create_ab_campaign()
        response = self._set_variants(campaign, split_a=50, split_b=40)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CampaignVariant.objects.filter(campaign=campaign).count(), 0)

    def test_set_variants_rejected_on_normal_campaign(self):
        url = reverse("campaign-list")
        payload = {
            "name": "Normal", "subject": "Hi", "sender_name": "Me", "sender_email": "me@example.com",
            "template": self.template_a.id, "contact_lists": [self.contact_list.id],
        }
        create = self.client.post(url, payload, format="json")
        campaign = Campaign.objects.get(id=create.data["id"])
        response = self._set_variants(campaign)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_set_variants_on_non_draft_campaign(self):
        campaign = self._create_ab_campaign()
        self._set_variants(campaign)
        campaign.status = Campaign.Status.SENT
        campaign.save(update_fields=["status"])
        response = self._set_variants(campaign, split_a=30, split_b=70)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- Sending / audience split ------------------------------------------

    def test_send_now_fails_without_both_variants_configured(self):
        campaign = self._create_ab_campaign()
        send_url = reverse("campaign-send-now", args=[campaign.id])
        response = self.client.post(send_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_now_splits_audience_and_every_contact_gets_exactly_one_variant(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        campaign = self._create_ab_campaign()
        self._set_variants(campaign, split_a=30, split_b=70)

        send_url = reverse("campaign-send-now", args=[campaign.id])
        response = self.client.post(send_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        recipients = CampaignRecipient.objects.filter(campaign=campaign)
        self.assertEqual(recipients.count(), 10)
        # Every recipient assigned to exactly one variant -- none left null.
        self.assertEqual(recipients.filter(variant__isnull=True).count(), 0)
        a_count = recipients.filter(variant__label=CampaignVariant.Label.A).count()
        b_count = recipients.filter(variant__label=CampaignVariant.Label.B).count()
        self.assertEqual(a_count + b_count, 10)
        self.assertEqual(a_count, 3)  # round(10 * 30/100)
        self.assertEqual(b_count, 7)
        self.assertEqual(mock_send.call_count, 10)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_now_uses_each_recipients_own_variant_subject(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        campaign = self._create_ab_campaign()
        self._set_variants(campaign)
        self.client.post(reverse("campaign-send-now", args=[campaign.id]))

        sent_subjects = {call.kwargs["subject"] for call in mock_send.call_args_list}
        self.assertEqual(sent_subjects, {"Subject A", "Subject B"})

    # -- Preview -----------------------------------------------------------

    def test_preview_returns_requested_variant_content(self):
        campaign = self._create_ab_campaign()
        self._set_variants(campaign)

        url = reverse("campaign-preview", args=[campaign.id])
        response_a = self.client.get(url, {"variant": "A"})
        response_b = self.client.get(url, {"variant": "B"})

        self.assertEqual(response_a.data["subject"], "Subject A")
        self.assertIn("Hello A", response_a.data["html_content"])
        self.assertEqual(response_b.data["subject"], "Subject B")
        self.assertIn("Hello B", response_b.data["html_content"])

    # -- Results -------------------------------------------------------------

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_ab_results_reflect_real_recipient_statuses_per_variant(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        campaign = self._create_ab_campaign()
        self._set_variants(campaign, split_a=50, split_b=50)
        self.client.post(reverse("campaign-send-now", args=[campaign.id]))

        # Simulate one Version A recipient opening their email (as the
        # webhook handler would do -- see brevo/webhooks.py), same as any
        # normal campaign's tracking.
        variant_a_recipient = CampaignRecipient.objects.filter(campaign=campaign, variant__label="A").first()
        variant_a_recipient.status = CampaignRecipient.Status.OPENED
        variant_a_recipient.save(update_fields=["status"])

        url = reverse("campaign-ab-results", args=[campaign.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        by_variant = {row["variant"]: row for row in response.data}
        self.assertEqual(by_variant["A"]["sent"], 5)
        self.assertEqual(by_variant["A"]["opened"], 1)
        self.assertEqual(by_variant["B"]["sent"], 5)
        self.assertEqual(by_variant["B"]["opened"], 0)

    def test_ab_results_rejected_for_normal_campaign(self):
        url = reverse("campaign-list")
        payload = {
            "name": "Normal", "subject": "Hi", "sender_name": "Me", "sender_email": "me@example.com",
            "template": self.template_a.id, "contact_lists": [self.contact_list.id],
        }
        create = self.client.post(url, payload, format="json")
        response = self.client.get(reverse("campaign-ab-results", args=[create.data["id"]]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- Duplication ---------------------------------------------------------

    def test_duplicate_ab_campaign_clones_variants(self):
        campaign = self._create_ab_campaign()
        self._set_variants(campaign, split_a=30, split_b=70)

        url = reverse("campaign-duplicate", args=[campaign.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        clone = Campaign.objects.get(id=response.data["id"])
        self.assertEqual(clone.campaign_type, Campaign.CampaignType.AB_TEST)
        self.assertEqual(clone.ab_variants.count(), 2)
        self.assertEqual(clone.ab_variants.get(label="A").split_percentage, 30)
