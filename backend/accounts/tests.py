from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthenticationTests(APITestCase):
    def setUp(self):
        self.register_url = reverse("auth-register")
        self.login_url = reverse("auth-login")
        self.logout_url = reverse("auth-logout")
        self.me_url = reverse("auth-me")
        self.valid_payload = {
            "username": "janedoe",
            "email": "jane@example.com",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
            "first_name": "Jane",
            "last_name": "Doe",
        }

    def test_register_creates_user_and_returns_tokens(self):
        response = self.client.post(self.register_url, self.valid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertTrue(User.objects.filter(email="jane@example.com").exists())

    def test_register_rejects_mismatched_passwords(self):
        payload = {**self.valid_payload, "password_confirm": "different"}
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_duplicate_email(self):
        self.client.post(self.register_url, self.valid_payload, format="json")
        response = self.client.post(self.register_url, self.valid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_with_username(self):
        self.client.post(self.register_url, self.valid_payload, format="json")
        response = self.client.post(
            self.login_url, {"username": "janedoe", "password": "S3curePass!23"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_login_with_email(self):
        self.client.post(self.register_url, self.valid_payload, format="json")
        response = self.client.post(
            self.login_url, {"username": "jane@example.com", "password": "S3curePass!23"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_invalid_credentials(self):
        response = self.client.post(
            self.login_url, {"username": "nobody", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_authentication(self):
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_current_user(self):
        self.client.post(self.register_url, self.valid_payload, format="json")
        login = self.client.post(
            self.login_url, {"username": "janedoe", "password": "S3curePass!23"}, format="json"
        )
        access = login.data["access"]
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "jane@example.com")

    def test_logout_blacklists_refresh_token(self):
        self.client.post(self.register_url, self.valid_payload, format="json")
        login = self.client.post(
            self.login_url, {"username": "janedoe", "password": "S3curePass!23"}, format="json"
        )
        access, refresh = login.data["access"], login.data["refresh"]
        response = self.client.post(
            self.logout_url, {"refresh": refresh}, format="json", HTTP_AUTHORIZATION=f"Bearer {access}"
        )
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)
