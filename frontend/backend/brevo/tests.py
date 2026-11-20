from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from analytics.models import CampaignEvent
from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact
from contacts.services_suppression import is_suppressed
from email_templates.models import EmailTemplate

User = get_user_model()


@override_settings(BREVO_WEBHOOK_SECRET="test-secret")
class BrevoWebhookTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        self.campaign = Campaign.objects.create(
            name="Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user, status=Campaign.Status.SENT,
        )
        self.contact = Contact.objects.create(owner=self.user, email="recipient@example.com")
        self.recipient = CampaignRecipient.objects.create(
            campaign=self.campaign, contact=self.contact, status=CampaignRecipient.Status.SENT
        )
        self.url = reverse("brevo-webhook")

    def _payload(self, event="delivered", message_id="msg-1"):
        return {
            "event": event,
            "email": self.contact.email,
            "message-id": message_id,
            "date": "2026-01-01 10:00:00",
            "tags": [f"campaign-{self.campaign.id}"],
            "headers": {"X-Campaign-Id": str(self.campaign.id), "X-Recipient-Id": str(self.recipient.id)},
        }

    def test_rejects_unauthorized_request(self):
        response = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_processes_delivered_event(self):
        response = self.client.post(
            self.url, self._payload(), format="json", HTTP_X_WEBHOOK_SECRET="test-secret"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, CampaignRecipient.Status.DELIVERED)
        self.assertEqual(CampaignEvent.objects.count(), 1)

    def test_duplicate_event_is_idempotent(self):
        headers = {"HTTP_X_WEBHOOK_SECRET": "test-secret"}
        self.client.post(self.url, self._payload(), format="json", **headers)
        self.client.post(self.url, self._payload(), format="json", **headers)
        self.assertEqual(CampaignEvent.objects.count(), 1)

    def test_hard_bounce_creates_suppression(self):
        response = self.client.post(
            self.url, self._payload(event="hard_bounce", message_id="msg-2"),
            format="json", HTTP_X_WEBHOOK_SECRET="test-secret",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(is_suppressed(self.contact.email))

    def test_unsubscribed_creates_suppression_and_updates_status(self):
        self.client.post(
            self.url, self._payload(event="unsubscribed", message_id="msg-3"),
            format="json", HTTP_X_WEBHOOK_SECRET="test-secret",
        )
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, CampaignRecipient.Status.UNSUBSCRIBED)
        self.assertTrue(is_suppressed(self.contact.email))


class BrevoServiceMockedTests(APITestCase):
    """Ensures our service layer never hits the real Brevo API in tests."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner2", email="owner2@example.com", password="pass12345!")
        self.template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        self.campaign = Campaign.objects.create(
            name="Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user,
        )

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_test_email_calls_client_not_real_api(self, mock_send):
        from brevo.services import send_test_email

        mock_send.return_value = {"messageId": "abc123"}
        result = send_test_email(self.campaign, "test@example.com")
        self.assertEqual(result["messageId"], "abc123")
        mock_send.assert_called_once()

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_to_recipient_includes_list_unsubscribe_headers(self, mock_send):
        from campaigns.models import CampaignRecipient
        from brevo.services import send_to_recipient

        contact = Contact.objects.create(owner=self.user, email="recipient@example.com")
        recipient = CampaignRecipient.objects.create(campaign=self.campaign, contact=contact)
        mock_send.return_value = {"messageId": "abc123"}

        send_to_recipient(self.campaign, recipient)

        _, kwargs = mock_send.call_args
        self.assertIn("List-Unsubscribe", kwargs["headers"])
        self.assertIn("List-Unsubscribe-Post", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        # The unsubscribe URL in the header should be resolvable back to this contact+campaign.
        from contacts.unsubscribe import parse_unsubscribe_token

        url = kwargs["headers"]["List-Unsubscribe"].strip("<>")
        token = url.rstrip("/").rsplit("/", 1)[-1]
        payload = parse_unsubscribe_token(token)
        self.assertEqual(payload["contact_id"], contact.id)
        self.assertEqual(payload["campaign_id"], self.campaign.id)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_to_recipient_replaces_unsubscribe_merge_tag(self, mock_send):
        from campaigns.models import CampaignRecipient
        from brevo.services import send_to_recipient

        self.template.html_content = '<p>Bye? <a href="{{unsubscribe_url}}">Unsubscribe</a></p>'
        self.template.save()
        contact = Contact.objects.create(owner=self.user, email="recipient2@example.com")
        recipient = CampaignRecipient.objects.create(campaign=self.campaign, contact=contact)
        mock_send.return_value = {"messageId": "abc123"}

        send_to_recipient(self.campaign, recipient)

        _, kwargs = mock_send.call_args
        self.assertNotIn("{{unsubscribe_url}}", kwargs["html_content"])
        self.assertIn("/api/unsubscribe/", kwargs["html_content"])

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_send_test_email_does_not_leak_real_unsubscribe_link(self, mock_send):
        from brevo.services import send_test_email

        self.template.html_content = '<a href="{{unsubscribe_url}}">Unsubscribe</a>'
        self.template.save()
        mock_send.return_value = {"messageId": "abc123"}

        send_test_email(self.campaign, "test@example.com")

        _, kwargs = mock_send.call_args
        self.assertNotIn("{{unsubscribe_url}}", kwargs["html_content"])
        self.assertNotIn("/api/unsubscribe/", kwargs["html_content"])
        self.assertNotIn("headers", kwargs)