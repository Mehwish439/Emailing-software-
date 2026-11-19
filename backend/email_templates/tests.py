from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import EmailTemplate, TemplateImage

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


class TemplateImageUploadTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.upload_url = reverse("template-image-upload")

    def _tiny_png(self):
        # A real 1x1 transparent PNG, valid enough for content-type sniffing purposes.
        content = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000100"
            "5f9f9ec80000000049454e44ae426082"
        )
        return SimpleUploadedFile("logo.png", content, content_type="image/png")

    def test_upload_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.upload_url, {"file": self._tiny_png()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_successful_upload_returns_public_url(self):
        response = self.client.post(self.upload_url, {"file": self._tiny_png()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("url", response.data)
        self.assertIn("/api/templates/images/", response.data["url"])
        self.assertEqual(TemplateImage.objects.count(), 1)
        self.assertEqual(TemplateImage.objects.first().owner, self.user)

    def test_rejects_disallowed_content_type(self):
        bad_file = SimpleUploadedFile("script.txt", b"not an image", content_type="text/plain")
        response = self.client.post(self.upload_url, {"file": bad_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TemplateImage.objects.count(), 0)

    def test_rejects_oversized_file(self):
        from email_templates.views import MAX_UPLOAD_SIZE_BYTES

        oversized = SimpleUploadedFile("big.png", b"0" * (MAX_UPLOAD_SIZE_BYTES + 1), content_type="image/png")
        response = self.client.post(self.upload_url, {"file": oversized}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TemplateImage.objects.count(), 0)

    def test_content_endpoint_serves_image_without_auth(self):
        upload = self.client.post(self.upload_url, {"file": self._tiny_png()}, format="multipart")
        image_id = upload.data["id"]

        self.client.force_authenticate(user=None)  # simulate a recipient's email client, not our frontend
        response = self.client.get(reverse("template-image-content", args=[image_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_content_endpoint_404s_for_unknown_id(self):
        response = self.client.get(reverse("template-image-content", args=[999999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)