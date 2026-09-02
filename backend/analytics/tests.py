from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate

User = get_user_model()


class AnalyticsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        self.contact_list = ContactList.objects.create(owner=self.user, name="Main")
        self.campaign = Campaign.objects.create(
            name="Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user, status=Campaign.Status.SENT,
        )
        contacts = [Contact.objects.create(owner=self.user, email=f"c{i}@example.com") for i in range(4)]
        statuses = [
            CampaignRecipient.Status.DELIVERED, CampaignRecipient.Status.OPENED,
            CampaignRecipient.Status.CLICKED, CampaignRecipient.Status.BOUNCED,
        ]
        for contact, st in zip(contacts, statuses):
            CampaignRecipient.objects.create(campaign=self.campaign, contact=contact, status=st)

    def test_dashboard_summary(self):
        url = reverse("analytics-dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_campaigns"], 1)
        self.assertEqual(response.data["emails_sent"], 4)

    def test_campaign_analytics_rates(self):
        url = reverse("analytics-campaign", args=[self.campaign.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["sent"], 4)
        self.assertEqual(response.data["delivered"], 3)  # delivered+opened+clicked
        self.assertEqual(response.data["clicked"], 1)
        self.assertGreater(response.data["delivery_rate"], 0)

    def test_campaign_analytics_not_found_for_other_user(self):
        other = User.objects.create_user(username="other", email="other@example.com", password="pass12345!")
        self.client.force_authenticate(user=other)
        url = reverse("analytics-campaign", args=[self.campaign.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
