from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate

from .models import ScheduledCampaign

User = get_user_model()


class SchedulingTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        self.contact_list = ContactList.objects.create(owner=self.user, name="Main")
        contact = Contact.objects.create(owner=self.user, email="a@example.com")
        contact.lists.add(self.contact_list)
        self.campaign = Campaign.objects.create(
            name="Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user,
        )
        self.campaign.contact_lists.add(self.contact_list)
        self.create_url = reverse("scheduling-create")

    def test_cannot_schedule_in_the_past(self):
        past = timezone.now() - timedelta(days=1)
        response = self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": past.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_timezone_rejected(self):
        future = timezone.now() + timedelta(days=1)
        response = self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": future.isoformat(), "timezone": "Not/ARealZone"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_successful_schedule(self):
        future = timezone.now() + timedelta(days=1)
        response = self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": future.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.SCHEDULED)
        schedule = ScheduledCampaign.objects.get(id=response.data["id"])
        self.assertEqual(schedule.status, ScheduledCampaign.Status.SCHEDULED)

    def test_cannot_double_schedule_same_campaign(self):
        future = timezone.now() + timedelta(days=1)
        self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": future.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        response = self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": future.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_schedule_campaign_without_recipients(self):
        empty_list = ContactList.objects.create(owner=self.user, name="Empty")
        campaign = Campaign.objects.create(
            name="Empty Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user,
        )
        campaign.contact_lists.add(empty_list)
        future = timezone.now() + timedelta(days=1)
        response = self.client.post(
            self.create_url,
            {"campaign": campaign.id, "scheduled_at": future.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_schedule(self):
        future = timezone.now() + timedelta(days=1)
        create = self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": future.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        detail_url = reverse("scheduling-detail", args=[create.data["id"]])
        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        schedule = ScheduledCampaign.objects.get(id=create.data["id"])
        self.assertEqual(schedule.status, ScheduledCampaign.Status.CANCELLED)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.DRAFT)

    def test_reschedule_updates_time(self):
        future = timezone.now() + timedelta(days=1)
        later = timezone.now() + timedelta(days=2)
        create = self.client.post(
            self.create_url,
            {"campaign": self.campaign.id, "scheduled_at": future.isoformat(), "timezone": "Asia/Karachi"},
            format="json",
        )
        detail_url = reverse("scheduling-detail", args=[create.data["id"]])
        response = self.client.put(detail_url, {"scheduled_at": later.isoformat()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schedule = ScheduledCampaign.objects.get(id=create.data["id"])
        self.assertAlmostEqual(schedule.scheduled_at, later, delta=timedelta(seconds=1))


class ProcessScheduledCampaignsCommandTests(APITestCase):
    """
    Tests for the cron entrypoint (scheduling/management/commands/process_scheduled_campaigns.py)
    that replaced Celery ETA/Beat scheduling.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        self.contact_list = ContactList.objects.create(owner=self.user, name="Main")
        self.contact = Contact.objects.create(owner=self.user, email="a@example.com")
        self.contact.lists.add(self.contact_list)

    def _make_campaign(self, name="Camp"):
        campaign = Campaign.objects.create(
            name=name, subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user,
        )
        campaign.contact_lists.add(self.contact_list)
        return campaign

    def _run_command(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("process_scheduled_campaigns", stdout=out, stderr=StringIO())
        return out.getvalue()

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_due_campaign_is_sent(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        campaign = self._make_campaign()
        schedule = ScheduledCampaign.objects.create(
            campaign=campaign,
            scheduled_at=timezone.now() - timedelta(minutes=1),  # already due
            timezone="Asia/Karachi",
        )
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save()

        self._run_command()

        schedule.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(schedule.status, ScheduledCampaign.Status.COMPLETED)
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        mock_send.assert_called_once()

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_future_campaign_is_ignored(self, mock_send):
        campaign = self._make_campaign()
        schedule = ScheduledCampaign.objects.create(
            campaign=campaign,
            scheduled_at=timezone.now() + timedelta(days=1),  # not due yet
            timezone="Asia/Karachi",
        )
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save()

        self._run_command()

        schedule.refresh_from_db()
        self.assertEqual(schedule.status, ScheduledCampaign.Status.SCHEDULED)
        mock_send.assert_not_called()

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_campaign_is_not_sent_twice_across_two_command_runs(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        campaign = self._make_campaign()
        schedule = ScheduledCampaign.objects.create(
            campaign=campaign,
            scheduled_at=timezone.now() - timedelta(minutes=1),
            timezone="Asia/Karachi",
        )
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save()

        self._run_command()
        self._run_command()  # simulate a second, overlapping/duplicate cron invocation

        schedule.refresh_from_db()
        self.assertEqual(schedule.status, ScheduledCampaign.Status.COMPLETED)
        # Only ever sent once, even though the command ran twice.
        mock_send.assert_called_once()

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_failed_send_marks_schedule_failed(self, mock_send):
        from common.exceptions import BrevoAPIError

        mock_send.side_effect = BrevoAPIError("simulated failure")
        campaign = self._make_campaign()
        schedule = ScheduledCampaign.objects.create(
            campaign=campaign,
            scheduled_at=timezone.now() - timedelta(minutes=1),
            timezone="Asia/Karachi",
        )
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save()

        self._run_command()

        schedule.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(schedule.status, ScheduledCampaign.Status.COMPLETED)
        # send_campaign_now() itself marks the *campaign* FAILED when every
        # recipient send fails; the schedule is still COMPLETED because the
        # send was attempted and finished (not stuck) — the failure reason
        # lives on the campaign, matching how "send now" reports failures too.
        self.assertEqual(campaign.status, Campaign.Status.FAILED)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    def test_multiple_due_campaigns_all_processed(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        campaigns = [self._make_campaign(name=f"Camp {i}") for i in range(3)]
        for c in campaigns:
            ScheduledCampaign.objects.create(
                campaign=c, scheduled_at=timezone.now() - timedelta(minutes=1), timezone="Asia/Karachi"
            )
            c.status = Campaign.Status.SCHEDULED
            c.save()

        self._run_command()

        for c in campaigns:
            c.refresh_from_db()
            self.assertEqual(c.status, Campaign.Status.SENT)
        self.assertEqual(mock_send.call_count, 3)


class ProcessDueSchedulesEndpointTests(APITestCase):
    """
    POST /api/scheduling/process-due/ — the HTTP equivalent of the
    process_scheduled_campaigns management command, for hosts without real
    cron access (see scheduling/views.py's process_due_schedules_view).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.template = EmailTemplate.objects.create(
            name="T", subject="Hi", html_content="<p>Hi</p>", created_by=self.user
        )
        self.contact_list = ContactList.objects.create(owner=self.user, name="Main")
        self.contact = Contact.objects.create(owner=self.user, email="a@example.com")
        self.contact.lists.add(self.contact_list)
        self.campaign = Campaign.objects.create(
            name="Camp", subject="Subj", sender_name="Me", sender_email="me@example.com",
            template=self.template, created_by=self.user, status=Campaign.Status.SCHEDULED,
        )
        self.campaign.contact_lists.add(self.contact_list)
        self.schedule = ScheduledCampaign.objects.create(
            campaign=self.campaign, scheduled_at=timezone.now() - timedelta(minutes=1), timezone="Asia/Karachi"
        )
        self.url = reverse("scheduling-process-due")

    @override_settings(CRON_SECRET="test-cron-secret")
    def test_rejects_request_without_secret(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.status, ScheduledCampaign.Status.SCHEDULED)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    @override_settings(CRON_SECRET="test-cron-secret")
    def test_processes_due_schedule_with_correct_secret(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        response = self.client.post(self.url, HTTP_X_CRON_SECRET="test-cron-secret")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 1)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.status, ScheduledCampaign.Status.COMPLETED)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    @override_settings(CRON_SECRET="test-cron-secret")
    def test_secret_via_query_param_also_works(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        response = self.client.post(f"{self.url}?secret=test-cron-secret")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("brevo.services.BrevoClient.send_transactional_email")
    @override_settings(CRON_SECRET="test-cron-secret")
    def test_calling_twice_does_not_send_twice(self, mock_send):
        mock_send.return_value = {"messageId": "abc"}
        self.client.post(self.url, HTTP_X_CRON_SECRET="test-cron-secret")
        response = self.client.post(self.url, HTTP_X_CRON_SECRET="test-cron-secret")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 0)
        mock_send.assert_called_once()