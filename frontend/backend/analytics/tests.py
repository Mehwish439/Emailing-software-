from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate

from .models import CampaignEvent

User = get_user_model()


class AnalyticsTestsBase(APITestCase):
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


class AnalyticsTests(AnalyticsTestsBase):
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


class CampaignLinkBreakdownTests(AnalyticsTestsBase):
    """
    GET /api/analytics/campaigns/{id}/links/ — must never combine every
    link's clicks into one campaign-level number (see
    analytics/services.py's compute_campaign_link_breakdown), and must
    separate "unsubscribe link requests" (every GET, side-effect-free) from
    "confirmed unsubscribes" (an actual status change).
    """

    def _click_event(self, contact, url, is_bot=None):
        metadata = {"clicked_url": url}
        if is_bot is not None:
            metadata["is_bot"] = is_bot
        CampaignEvent.objects.create(
            campaign=self.campaign,
            contact=contact,
            event_type=CampaignEvent.EventType.CLICKED,
            timestamp=timezone.now(),
            metadata=metadata,
            dedupe_key=f"click-{contact.id}-{url}-{timezone.now().timestamp()}",
        )

    def test_clicks_are_broken_down_separately_per_url_not_combined(self):
        alice = Contact.objects.create(owner=self.user, email="alice@example.com")
        bob = Contact.objects.create(owner=self.user, email="bob@example.com")

        self._click_event(alice, "https://qualityresource.net/free-quote/")
        self._click_event(bob, "https://qualityresource.net/free-quote/")
        self._click_event(alice, "https://example.com/unsubscribe/token123/")

        url = reverse("analytics-campaign-links", args=[self.campaign.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        by_url = {link["url"]: link for link in response.data["links"]}
        self.assertEqual(by_url["https://qualityresource.net/free-quote/"]["total_clicks"], 2)
        self.assertEqual(by_url["https://qualityresource.net/free-quote/"]["unique_contacts"], 2)
        self.assertEqual(by_url["https://example.com/unsubscribe/token123/"]["total_clicks"], 1)

    def test_repeated_clicks_from_same_contact_count_once_as_unique(self):
        alice = Contact.objects.create(owner=self.user, email="alice2@example.com")
        for _ in range(5):
            self._click_event(alice, "https://qualityresource.net/free-quote/")

        url = reverse("analytics-campaign-links", args=[self.campaign.id])
        response = self.client.get(url)
        link = response.data["links"][0]
        self.assertEqual(link["total_clicks"], 5)
        self.assertEqual(link["unique_contacts"], 1)

    def test_bot_vs_human_click_breakdown(self):
        alice = Contact.objects.create(owner=self.user, email="alice3@example.com")
        bob = Contact.objects.create(owner=self.user, email="bob3@example.com")
        self._click_event(alice, "https://qualityresource.net/free-quote/", is_bot=False)
        self._click_event(bob, "https://qualityresource.net/free-quote/", is_bot=True)

        url = reverse("analytics-campaign-links", args=[self.campaign.id])
        response = self.client.get(url)
        link = response.data["links"][0]
        self.assertEqual(link["human_clicks"], 1)
        self.assertEqual(link["automated_clicks"], 1)

    def test_unsubscribe_requests_and_confirmations_are_reported_separately(self):
        alice = Contact.objects.create(owner=self.user, email="alice4@example.com")
        bob = Contact.objects.create(owner=self.user, email="bob4@example.com")

        # Two "views" (GETs) — one from a real browser, one from a scanner — neither confirmed.
        CampaignEvent.objects.create(
            campaign=self.campaign, contact=alice, event_type=CampaignEvent.EventType.UNSUBSCRIBE_VIEWED,
            timestamp=timezone.now(), metadata={"is_bot": False}, dedupe_key="view-1",
        )
        CampaignEvent.objects.create(
            campaign=self.campaign, contact=bob, event_type=CampaignEvent.EventType.UNSUBSCRIBE_VIEWED,
            timestamp=timezone.now(), metadata={"is_bot": True}, dedupe_key="view-2",
        )
        # Only alice actually confirmed.
        CampaignEvent.objects.create(
            campaign=self.campaign, contact=alice, event_type=CampaignEvent.EventType.UNSUBSCRIBED,
            timestamp=timezone.now(), metadata={}, dedupe_key="confirm-1",
        )

        url = reverse("analytics-campaign-links", args=[self.campaign.id])
        response = self.client.get(url)
        unsub = response.data["unsubscribe"]
        self.assertEqual(unsub["link_requests_total"], 2)
        self.assertEqual(unsub["estimated_human_requests"], 1)
        self.assertEqual(unsub["estimated_automated_requests"], 1)
        self.assertEqual(unsub["confirmed_unsubscribes"], 1)  # NOT 2 — views alone don't count as confirmed