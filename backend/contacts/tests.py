import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Contact, ContactList
from .services_suppression import is_suppressed

User = get_user_model()


class ContactTestsBase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)


class ContactCRUDTests(ContactTestsBase):
    def test_create_contact(self):
        url = reverse("contact-list")
        response = self.client.post(url, {"first_name": "A", "last_name": "B", "email": "a@example.com"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Contact.objects.count(), 1)

    def test_duplicate_email_rejected(self):
        Contact.objects.create(owner=self.user, email="dup@example.com")
        url = reverse("contact-list")
        response = self.client.post(url, {"email": "dup@example.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_contacts(self):
        Contact.objects.create(owner=self.user, email="findme@example.com", first_name="Findable")
        Contact.objects.create(owner=self.user, email="other@example.com", first_name="Other")
        url = reverse("contact-list")
        response = self.client.get(url, {"search": "Findable"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_bulk_delete(self):
        c1 = Contact.objects.create(owner=self.user, email="c1@example.com")
        c2 = Contact.objects.create(owner=self.user, email="c2@example.com")
        url = reverse("contact-bulk-delete")
        response = self.client.post(url, {"ids": [c1.id, c2.id]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Contact.objects.count(), 0)

    def test_add_and_remove_from_list(self):
        clist = ContactList.objects.create(owner=self.user, name="VIPs")
        contact = Contact.objects.create(owner=self.user, email="vip@example.com")
        add_url = reverse("contact-add-to-list")
        response = self.client.post(add_url, {"list_id": clist.id, "contact_ids": [contact.id]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(clist, contact.lists.all())

        remove_url = reverse("contact-remove-from-list")
        response = self.client.post(remove_url, {"list_id": clist.id, "contact_ids": [contact.id]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(clist, contact.lists.all())


class CSVImportTests(ContactTestsBase):
    def _upload(self, content):
        file_obj = SimpleUploadedFile("contacts.csv", content.encode("utf-8"), content_type="text/csv")
        url = reverse("contact-import-csv")
        return self.client.post(url, {"file": file_obj}, format="multipart")

    def test_import_valid_csv(self):
        csv_content = (
            "first_name,last_name,email,phone\n"
            "John,Doe,john@example.com,123\n"
            "Jane,Smith,jane@example.com,456\n"
        )
        response = self._upload(csv_content)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["imported"], 2)
        self.assertEqual(response.data["total_processed"], 2)

    def test_import_detects_invalid_and_duplicate(self):
        Contact.objects.create(owner=self.user, email="existing@example.com")
        csv_content = (
            "first_name,last_name,email,phone\n"
            "Bad,Email,not-an-email,000\n"
            "Existing,User,existing@example.com,111\n"
            "New,User,newuser@example.com,222\n"
        )
        response = self._upload(csv_content)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["imported"], 1)
        self.assertEqual(response.data["invalid"], 1)
        self.assertEqual(response.data["duplicates"], 1)
        self.assertEqual(response.data["total_processed"], 3)

    def test_import_rejects_missing_email_column(self):
        csv_content = "first_name,last_name\nJohn,Doe\n"
        response = self._upload(csv_content)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UnsubscribeEndpointTests(APITestCase):
    """Public one-click unsubscribe endpoint (contacts/unsubscribe.py + the view)."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.contact = Contact.objects.create(owner=self.user, email="subscriber@example.com")

    def _url(self, token):
        return reverse("unsubscribe", args=[token])

    def test_valid_token_unsubscribes_contact_no_auth_required(self):
        from contacts.unsubscribe import generate_unsubscribe_token

        token = generate_unsubscribe_token(self.contact.id)
        # No self.client.force_authenticate — this must work fully anonymously.
        response = self.client.get(self._url(token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(b"unsubscribed", response.content.lower())
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.status, Contact.Status.UNSUBSCRIBED)
        self.assertTrue(is_suppressed(self.contact.email))

    def test_one_click_post_unsubscribes_without_rendering_page(self):
        from contacts.unsubscribe import generate_unsubscribe_token

        token = generate_unsubscribe_token(self.contact.id)
        response = self.client.post(self._url(token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.status, Contact.Status.UNSUBSCRIBED)

    def test_invalid_token_rejected(self):
        response = self.client.get(self._url("not-a-real-token"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # renders a friendly error page, not a 4xx
        self.assertIn(b"invalid", response.content.lower())
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.status, Contact.Status.ACTIVE)  # untouched

    def test_unsubscribe_updates_campaign_recipient_and_event(self):
        from analytics.models import CampaignEvent
        from campaigns.models import Campaign, CampaignRecipient
        from contacts.unsubscribe import generate_unsubscribe_token
        from email_templates.models import EmailTemplate

        template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        campaign = Campaign.objects.create(
            name="Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=template, created_by=self.user, status=Campaign.Status.SENT,
        )
        recipient = CampaignRecipient.objects.create(
            campaign=campaign, contact=self.contact, status=CampaignRecipient.Status.SENT
        )

        token = generate_unsubscribe_token(self.contact.id, campaign.id)
        response = self.client.get(self._url(token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, CampaignRecipient.Status.UNSUBSCRIBED)
        self.assertTrue(
            CampaignEvent.objects.filter(
                campaign=campaign, contact=self.contact, event_type=CampaignEvent.EventType.UNSUBSCRIBED
            ).exists()
        )

    def test_clicking_twice_is_idempotent(self):
        from contacts.unsubscribe import generate_unsubscribe_token

        token = generate_unsubscribe_token(self.contact.id)
        self.client.get(self._url(token))
        response = self.client.get(self._url(token))  # click the same link again
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.status, Contact.Status.UNSUBSCRIBED)