"""
Thin HTTP client around the Brevo (Sendinblue) REST API.
Contains no business logic — just request/response handling for the endpoints
this platform needs. All business logic lives in brevo/services.py.
"""
import logging

import requests
from django.conf import settings

from common.exceptions import BrevoAPIError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15  # seconds


class BrevoClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or settings.BREVO_API_KEY
        self.base_url = (base_url or settings.BREVO_API_BASE_URL).rstrip("/")

    def _headers(self):
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": self.api_key,
        }

    def _request(self, method, path, **kwargs):
        if not self.api_key:
            raise BrevoAPIError("BREVO_API_KEY is not configured.")
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method, url, headers=self._headers(), timeout=DEFAULT_TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            logger.error("Brevo request failed: %s %s -> %s", method, url, exc)
            raise BrevoAPIError(f"Could not reach Brevo API: {exc}") from exc

        if response.status_code >= 400:
            logger.error("Brevo API error %s: %s", response.status_code, response.text[:500])
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text}
            raise BrevoAPIError(
                payload.get("message", "Brevo API request failed"),
                status_code=response.status_code,
                payload=payload,
            )

        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    # ------------------------------------------------------------------
    # Transactional email (used for test sends and per-recipient sending)
    # ------------------------------------------------------------------
    def send_transactional_email(self, sender, to, subject, html_content, tags=None, headers=None):
        """
        POST /smtp/email
        sender: {"name": ..., "email": ...}
        to: [{"email": ..., "name": ...}, ...]
        """
        payload = {
            "sender": sender,
            "to": to,
            "subject": subject,
            "htmlContent": html_content,
        }
        if tags:
            payload["tags"] = tags
        if headers:
            payload["headers"] = headers
        return self._request("POST", "/smtp/email", json=payload)

    # ------------------------------------------------------------------
    # Email campaigns (Brevo's native campaign object, used for
    # provider-side tracking/reporting parity)
    # ------------------------------------------------------------------
    def create_email_campaign(self, name, subject, sender, html_content, recipient_list_ids=None):
        payload = {
            "name": name,
            "subject": subject,
            "sender": sender,
            "htmlContent": html_content,
            "type": "classic",
        }
        if recipient_list_ids:
            payload["recipients"] = {"listIds": recipient_list_ids}
        return self._request("POST", "/emailCampaigns", json=payload)

    def send_email_campaign_now(self, brevo_campaign_id):
        return self._request("POST", f"/emailCampaigns/{brevo_campaign_id}/sendNow")

    def get_email_campaign(self, brevo_campaign_id):
        return self._request("GET", f"/emailCampaigns/{brevo_campaign_id}")

    # ------------------------------------------------------------------
    # Contacts (optional sync — used for suppression/list parity)
    # ------------------------------------------------------------------
    def get_contact(self, email):
        return self._request("GET", f"/contacts/{email}")
