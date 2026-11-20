from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate

from .models import Campaign, CampaignRecipient

User = get_user_model()


class CampaignTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.template = EmailTemplate.objects.create(
            name="Welcome", subject="Hi", html_content="<p>Hello</p>", created_by=self.user
        )
        self.contact_list = ContactList.objects.create(owner=self.user, name="Main")
        self.contact = Contact.objects.create(owner=self.user, email="a@example.com")
        self.contact.lists.add(self.contact_list)

    def _create_campaign(self):
        url = reverse("campaign-list")
        payload = {
            "name": "August Newsletter",
            "subject": "Hello!",
            "sender_name": "Me",
            "sender_email": "me@example.com",
            "template": self.template.id,
            "contact_lists": [self.contact_list.id],
        }
        return self.client.post(url, payload, format="json")

    def test_create_campaign(self):
        response = self._create_campaign()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "draft")

    def test_cannot_edit_non_draft_campaign(self):
        response = self._create_campaign()
        campaign = Campaign.objects.get(id=response.data["id"])
        campaign.status = Campaign.Status.SENT
        campaign.save()
        url = reverse("campaign-detail", args=[campaign.id])
        response = self.client.patch(url, {"name": "New name"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_now_fails_without_recipients(self):
        empty_list = ContactList.objects.create(owner=self.user, name="Empty")
        url = reverse("campaign-list")
        payload = {
            "name": "Empty Campaign", "subject": "Hi", "sender_name": "Me", "sender_email": "me@example.com",
            "template": self.template.id, "contact_lists": [empty_list.id],
        }
        create = self.client.post(url, payload, format="json")
        send_url = reverse("campaign-send-now", args=[create.data["id"]])
        response = self.client.post(send_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_now_dispatches_to_recipients(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        create = self._create_campaign()
        send_url = reverse("campaign-send-now", args=[create.data["id"]])
        # send_campaign_now() is fully synchronous now (no task queue), so the
        # response only comes back after the send has actually completed.
        response = self.client.post(send_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "sent")
        campaign = Campaign.objects.get(id=create.data["id"])
        recipient = CampaignRecipient.objects.get(campaign=campaign, contact=self.contact)
        self.assertEqual(recipient.status, CampaignRecipient.Status.SENT)
        mock_send.assert_called_once()

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_now_marks_campaign_failed_when_all_recipients_fail(self, mock_send):
        from common.exceptions import BrevoAPIError

        mock_send.side_effect = BrevoAPIError("simulated failure")
        create = self._create_campaign()
        send_url = reverse("campaign-send-now", args=[create.data["id"]])
        response = self.client.post(send_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign = Campaign.objects.get(id=create.data["id"])
        self.assertEqual(campaign.status, Campaign.Status.FAILED)
        recipient = CampaignRecipient.objects.get(campaign=campaign, contact=self.contact)
        self.assertEqual(recipient.status, CampaignRecipient.Status.FAILED)
        # MAX_SEND_ATTEMPTS retries per recipient before giving up.
        self.assertEqual(mock_send.call_count, 2)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_test_email(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        create = self._create_campaign()
        url = reverse("campaign-send-test", args=[create.data["id"]])
        response = self.client.post(url, {"test_email": "tester@example.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send.assert_called_once()

    def test_duplicate_campaign(self):
        create = self._create_campaign()
        url = reverse("campaign-duplicate", args=[create.data["id"]])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Campaign.objects.count(), 2)

    def test_cannot_delete_sent_campaign(self):
        create = self._create_campaign()
        campaign = Campaign.objects.get(id=create.data["id"])
        campaign.status = Campaign.Status.SENT
        campaign.save()
        url = reverse("campaign-detail", args=[campaign.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)