from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import EmailTemplate

User = get_user_model()


class EmailTemplateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)

    def test_create_template(self):
        url = reverse("template-list")
        response = self.client.post(
            url, {"name": "Welcome", "subject": "Hi!", "html_content": "<p>Hello</p>"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_empty_content_rejected(self):
        url = reverse("template-list")
        response = self.client.post(url, {"name": "Empty", "subject": "Hi", "html_content": "   "})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_template(self):
        template = EmailTemplate.objects.create(
            name="Original", subject="Subj", html_content="<p>X</p>", created_by=self.user
        )
        url = reverse("template-duplicate", args=[template.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(EmailTemplate.objects.count(), 2)

    def test_preview_template(self):
        template = EmailTemplate.objects.create(
            name="Original", subject="Subj", html_content="<p>X</p>", created_by=self.user
        )
        url = reverse("template-preview", args=[template.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["subject"], "Subj")
