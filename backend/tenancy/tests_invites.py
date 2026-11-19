"""Invitation, resend, platform-admin onboarding, forgot-password and soft-bounce escalation."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from analytics.models import CampaignEvent
from brevo.webhooks import escalate_soft_bounces
from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact, Suppression

from .models import AuditLog
from providers.tests import Fixture

from .tests import TenantBase

User = get_user_model()
MAIL = "tenancy.invites.send_link_email"


class CompanyInviteEmailTests(TenantBase):
    def setUp(self):
        super().setUp()
        self.plan.max_users = 10
        self.plan.save()
        self.login(self.acme_admin)

    def test_link_is_always_returned_to_the_admin_and_flags_whether_email_was_accepted(self):
        r = self.client.post("/api/company/members/", {"email": "a@example.com"}, format="json")
        self.assertFalse(r.data["email_sent"])
        self.assertIn("/join?token=", r.data["invite_url"])
        with patch(MAIL, return_value=True):
            r = self.client.post("/api/company/members/", {"email": "b@example.com"}, format="json")
        self.assertTrue(r.data["email_sent"])
        # the admin ALWAYS gets the link, even when the provider accepted the email (it may never arrive)
        self.assertIn("/join?token=", r.data["invite_url"])

    def test_resend_only_for_own_company_pending_users(self):
        pending = self.client.post("/api/company/members/", {"email": "p@example.com"}, format="json").data["user"]["id"]
        ok = self.client.post(f"/api/company/members/{pending}/resend-invite/")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("/join?token=", ok.data["invite_url"])
        self.assertTrue(AuditLog.objects.filter(action="user.invite_resent").exists())
        # already-active user: rejected
        self.assertEqual(self.client.post(f"/api/company/members/{self.acme_user.id}/resend-invite/").status_code, 400)
        # other company's user: 404, never reveals existence
        other = User(username="o@example.com", email="o@example.com", company=self.beta)
        other.set_unusable_password(); other.save()
        self.assertEqual(self.client.post(f"/api/company/members/{other.id}/resend-invite/").status_code, 404)

    def test_regular_user_cannot_resend(self):
        self.login(self.acme_user)
        self.assertEqual(self.client.post(f"/api/company/members/{self.acme_user.id}/resend-invite/").status_code, 403)

    def test_old_link_dies_after_password_is_set(self):
        r = self.client.post("/api/company/members/", {"email": "z@example.com"}, format="json")
        first = r.data["invite_url"].split("token=")[1]
        second = self.client.post(f"/api/company/members/{r.data['user']['id']}/resend-invite/").data["invite_url"].split("token=")[1]
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post("/api/auth/accept-invite/", {"token": second, "password": "Str0ng-Pass-123!"}, format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/accept-invite/", {"token": first, "password": "An0ther-Pass-456!"}, format="json").status_code, 400)

    def test_provider_failure_falls_back_to_showing_link(self):
        from brevo.client import BrevoClient

        with override_settings(SEND_INVITE_EMAILS=True, BREVO_API_KEY="k", BREVO_SENDER_EMAIL="s@example.com"), \
                patch.object(BrevoClient, "send_transactional_email", side_effect=RuntimeError("boom")):
            r = self.client.post("/api/company/members/", {"email": "f@example.com"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.data["email_sent"])
        self.assertIsNotNone(r.data["invite_url"])


class PlatformOnboardingTests(TenantBase):
    def test_platform_admin_invites_company_admin(self):
        self.login(self.root)
        r = self.client.post(f"/api/platform/companies/{self.beta.id}/members/", {"email": "Boss@Example.com", "first_name": "Boss"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        u = User.objects.get(email="boss@example.com")
        self.assertEqual((u.company_id, u.role), (self.beta.id, "company_admin"))
        self.assertFalse(u.has_usable_password())
        token = r.data["invite_url"].split("token=")[1]
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post("/api/auth/accept-invite/", {"token": token, "password": "Str0ng-Pass-123!"}, format="json").status_code, 200)
        self.client.force_authenticate(user=u)
        self.assertEqual(self.client.get("/api/company/overview/").status_code, 200)

    def test_cannot_create_super_admin_or_duplicate_or_exceed_seats(self):
        self.login(self.root)
        url = f"/api/platform/companies/{self.acme.id}/members/"
        self.assertEqual(self.client.post(url, {"email": "x@example.com", "role": "super_admin"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"email": "acme_user@example.com"}, format="json").status_code, 400)
        self.client.post(url, {"email": "seat3@example.com"}, format="json")             # fills the 3rd seat
        self.assertEqual(self.client.post(url, {"email": "seat4@example.com"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/platform/companies/99999/members/", {"email": "n@example.com"}, format="json").status_code, 404)

    def test_company_admin_and_user_cannot_use_it(self):
        for who in (self.acme_admin, self.acme_user):
            self.login(who)
            self.assertEqual(self.client.post(f"/api/platform/companies/{self.acme.id}/members/", {"email": "q@example.com"}, format="json").status_code, 403)


class ForgotPasswordTests(TenantBase):
    def test_same_answer_for_known_and_unknown_and_link_not_leaked(self):
        known = self.client.post("/api/auth/forgot-password/", {"email": "acme_user@example.com"}, format="json")
        unknown = self.client.post("/api/auth/forgot-password/", {"email": "nobody@example.com"}, format="json")
        self.assertEqual((known.status_code, known.data), (unknown.status_code, unknown.data))
        self.assertNotIn("token", str(known.data))

    def test_email_sent_only_for_active_accounts(self):
        self.acme_user.is_active = False; self.acme_user.save()
        with patch("tenancy.invites.send_link_email") as m:
            self.client.post("/api/auth/forgot-password/", {"email": "acme_user@example.com"}, format="json")
            self.assertFalse(m.called)
            self.client.post("/api/auth/forgot-password/", {"email": "acme_admin@example.com"}, format="json")
            self.assertTrue(m.called)


class SoftBounceEscalationTests(Fixture, APITestCase):
    def setUp(self):
        self.owner = self.make_user("own")
        self.campaign = self.make_campaign(self.owner, n=1)
        self.contact = Contact.objects.get(owner=self.owner)
        Contact.objects.filter(pk=self.contact.pk).update(email="slow@example.com")
        self.contact.refresh_from_db()

    def _event(self, kind, n, ago=0):
        CampaignEvent.objects.create(campaign=self.campaign, contact=self.contact, event_type=kind,
                                     timestamp=timezone.now() - timedelta(minutes=ago), dedupe_key=f"{kind}-{n}")

    @override_settings(SOFT_BOUNCE_SUPPRESS_THRESHOLD=3, SOFT_BOUNCE_WINDOW_DAYS=30)
    def test_three_consecutive_soft_bounces_suppress(self):
        for i in range(2):
            self._event("soft_bounce", i, ago=10 - i)
        self.assertFalse(escalate_soft_bounces("slow@example.com"))
        self.assertFalse(Suppression.objects.filter(email="slow@example.com").exists())
        self._event("soft_bounce", 2)
        self.assertTrue(escalate_soft_bounces("slow@example.com"))
        self.assertEqual(Suppression.objects.get(email="slow@example.com").reason, "soft_bounce_limit")

    @override_settings(SOFT_BOUNCE_SUPPRESS_THRESHOLD=3, SOFT_BOUNCE_WINDOW_DAYS=30)
    def test_a_delivery_resets_the_streak(self):
        self._event("soft_bounce", 0, ago=30); self._event("soft_bounce", 1, ago=20)
        self._event("delivered", 0, ago=10)
        self._event("soft_bounce", 2, ago=1)
        self.assertFalse(escalate_soft_bounces("slow@example.com"))
        self.assertFalse(Suppression.objects.filter(email="slow@example.com").exists())

    @override_settings(SOFT_BOUNCE_SUPPRESS_THRESHOLD=0)
    def test_threshold_zero_disables(self):
        for i in range(5):
            self._event("soft_bounce", i, ago=i)
        self.assertFalse(escalate_soft_bounces("slow@example.com"))

    @override_settings(SOFT_BOUNCE_SUPPRESS_THRESHOLD=3, SOFT_BOUNCE_WINDOW_DAYS=1)
    def test_old_bounces_outside_window_do_not_count(self):
        for i in range(4):
            self._event("soft_bounce", i, ago=60 * 24 * 5)
        self.assertFalse(escalate_soft_bounces("slow@example.com"))

    @override_settings(SOFT_BOUNCE_SUPPRESS_THRESHOLD=2)
    def test_webhook_path_escalates_and_duplicate_event_is_ignored(self):
        from brevo.webhooks import process_webhook_event

        rid = CampaignRecipient.objects.create(campaign=self.campaign, contact=self.contact).id
        def payload(mid):
            return {"event": "soft_bounce", "email": "slow@example.com", "message-id": mid,
                    "headers": {"X-Campaign-Id": str(self.campaign.id), "X-Recipient-Id": str(rid)}, "tags": [f"campaign-{self.campaign.id}"]}
        process_webhook_event(payload("<m1>"))
        self.assertEqual(process_webhook_event(payload("<m1>")), "duplicate-ignored")   # idempotent
        self.assertFalse(Suppression.objects.filter(email="slow@example.com").exists())
        process_webhook_event(payload("<m2>"))
        self.assertTrue(Suppression.objects.filter(email="slow@example.com", reason="soft_bounce_limit").exists())


class BrevoLiveHealthTests(TenantBase):
    """The health page must not report Brevo as OK merely because a key string exists."""

    def test_rejected_key_is_reported_as_failing_and_accepted_key_as_ok(self):
        from brevo.client import BrevoClient
        from common.exceptions import BrevoAPIError

        self.login(self.root)
        with patch.object(BrevoClient, "get_account", side_effect=BrevoAPIError("Key not found", status_code=401)):
            bad = self.client.get("/api/platform/health/").data["providers"]["brevo"]
        self.assertFalse(bad["ok"])
        self.assertIn("401", bad["detail"])
        with patch.object(BrevoClient, "get_account", return_value={"email": "x"}):
            good = self.client.get("/api/platform/health/").data["providers"]["brevo"]
        self.assertTrue(good["ok"])
        self.assertNotIn("test-placeholder", str(good))


class InviteEmailContentTests(TenantBase):
    def test_email_contains_the_real_absolute_join_link_twice(self):
        from brevo.client import BrevoClient

        self.plan.max_users = 10; self.plan.save()
        self.login(self.acme_admin)
        sent = {}
        with override_settings(SEND_INVITE_EMAILS=True, BREVO_API_KEY="k", BREVO_SENDER_EMAIL="s@example.com", FRONTEND_URL="https://app.example.com"), \
                patch.object(BrevoClient, "send_transactional_email", side_effect=lambda **kw: sent.update(kw) or {}):
            r = self.client.post("/api/company/members/", {"email": "mail@acme.test", "first_name": "Mia"}, format="json")
        self.assertTrue(r.data["email_sent"])
        self.assertTrue(r.data["invite_url"].startswith("https://app.example.com/join?token="))
        self.assertEqual(sent["html_content"].count(r.data["invite_url"]), 3)       # button href + visible link (text + href)
        self.assertEqual(sent["to"][0]["email"], "mail@acme.test")


class SuperuserRoleTests(TenantBase):
    def test_createsuperuser_account_is_a_platform_admin_in_the_api(self):
        su = User.objects.create_superuser("owner", "owner@example.com", "Str0ng-Pass-123!")
        self.assertEqual(su.role, "super_admin")
        r = self.client.post("/api/auth/login/", {"username": "owner@example.com", "password": "Str0ng-Pass-123!"}, format="json")
        self.assertEqual(r.data["user"]["role"], "super_admin")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(self.client.get("/api/platform/overview/").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").data["role"], "super_admin")

    def test_superuser_created_before_the_fix_is_reported_correctly(self):
        su = User.objects.create_superuser("old", "old@example.com", "Str0ng-Pass-123!")
        User.objects.filter(pk=su.pk).update(role="user")           # simulate legacy row
        self.client.force_authenticate(User.objects.get(pk=su.pk))
        self.assertEqual(self.client.get("/api/auth/me/").data["role"], "super_admin")