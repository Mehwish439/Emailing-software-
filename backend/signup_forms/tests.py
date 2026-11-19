# NEW FILE (Signup Forms feature)
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from contacts.models import Contact, ContactList, Tag

from .models import SignupForm

User = get_user_model()


class SignupFormManagementTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.other_user = User.objects.create_user(username="other", email="other@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.contact_list = ContactList.objects.create(owner=self.user, name="Newsletter Subscribers")
        self.tag = Tag.objects.create(owner=self.user, name="website-signup")

    def test_create_requires_list_or_tag(self):
        response = self.client.post(reverse("signup-form-list"), {"name": "No target"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_and_embed_code(self):
        response = self.client.post(
            reverse("signup-form-list"),
            {"name": "Newsletter Signup", "contact_list": self.contact_list.id, "tags": [self.tag.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("embed_code", response.data)
        self.assertIn(str(response.data["public_id"]), response.data["embed_code"])

    def test_cannot_select_another_owners_list(self):
        foreign_list = ContactList.objects.create(owner=self.other_user, name="Not yours")
        response = self.client.post(
            reverse("signup-form-list"), {"name": "Sneaky", "contact_list": foreign_list.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_is_scoped_to_owner(self):
        SignupForm.objects.create(owner=self.other_user, name="Someone else's form", contact_list=None).tags.set(
            [Tag.objects.create(owner=self.other_user, name="t")]
        )
        SignupForm.objects.create(owner=self.user, name="Mine", contact_list=self.contact_list)
        response = self.client.get(reverse("signup-form-list"))
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Mine")

    def test_management_endpoint_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("signup-form-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PublicSignupFormTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.contact_list = ContactList.objects.create(owner=self.user, name="Newsletter Subscribers")
        self.tag = Tag.objects.create(owner=self.user, name="website-signup")
        self.form = SignupForm.objects.create(owner=self.user, name="Newsletter Signup", contact_list=self.contact_list)
        self.form.tags.add(self.tag)
        self.detail_url = reverse("signup-form-public-detail", args=[self.form.public_id])
        self.submit_url = reverse("signup-form-public-submit", args=[self.form.public_id])

    def test_public_detail_excludes_private_fields(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for field in ("contact_list", "tags", "owner", "submission_count", "is_active"):
            self.assertNotIn(field, response.data)

    def test_public_detail_requires_no_auth(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unknown_form_id_is_404(self):
        import uuid

        response = self.client.get(reverse("signup-form-public-detail", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_form_is_404_for_detail_and_submit(self):
        self.form.is_active = False
        self.form.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.post(self.submit_url, {"email": "a@example.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_creates_contact_with_list_and_tags(self):
        response = self.client.post(
            self.submit_url,
            {"email": "New.Visitor@Example.com", "first_name": "New", "last_name": "Visitor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contact = Contact.objects.get(owner=self.user, email="new.visitor@example.com")
        self.assertIn(self.contact_list, contact.lists.all())
        self.assertIn(self.tag, contact.tags.all())
        self.form.refresh_from_db()
        self.assertEqual(self.form.submission_count, 1)

    def test_submit_invalid_email_rejected(self):
        response = self.client.post(self.submit_url, {"email": "not-an-email"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Contact.objects.filter(owner=self.user).count(), 0)

    def test_duplicate_submission_updates_instead_of_duplicating(self):
        self.client.post(self.submit_url, {"email": "dup@example.com", "first_name": "First"}, format="json")
        response = self.client.post(
            self.submit_url, {"email": "dup@example.com", "first_name": "Ignored"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contacts = Contact.objects.filter(owner=self.user, email="dup@example.com")
        self.assertEqual(contacts.count(), 1)
        # Existing non-blank name is never overwritten by a later submission.
        self.assertEqual(contacts.first().first_name, "First")
        self.form.refresh_from_db()
        self.assertEqual(self.form.submission_count, 2)

    def test_honeypot_silently_drops_submission(self):
        response = self.client.post(
            self.submit_url,
            {"email": "bot@example.com", "hp_field": "http://spam.example"},
            format="json",
        )
        # Looks like success to the caller, but nothing is actually created.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Contact.objects.filter(owner=self.user).count(), 0)
        self.form.refresh_from_db()
        self.assertEqual(self.form.submission_count, 0)

    def test_public_endpoints_allow_any_cross_origin(self):
        response = self.client.get(self.detail_url, HTTP_ORIGIN="https://some-customer-site.example")
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://some-customer-site.example")

    def test_unrelated_endpoints_do_not_get_wildcard_cors(self):
        response = self.client.get(reverse("contact-list"), HTTP_ORIGIN="https://some-customer-site.example")
        self.assertIsNone(response.get("Access-Control-Allow-Origin"))
