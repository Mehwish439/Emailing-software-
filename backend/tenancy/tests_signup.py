"""Company sign-up, invitation join, role integrity, and per-campaign provider choice."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from campaigns.models import Campaign
from campaigns.services import _claim_campaign_for_sending, send_campaign_now
from common.exceptions import ValidationAppError
from providers.base import SendResult
from providers.tests import Fixture

from .models import AuditLog, Company, PlatformSettings
from .tests import TenantBase

User = get_user_model()
GOOD = {"company_name": "Globex Ltd", "first_name": "Gina", "last_name": "Lee", "email": "Gina@Globex.test",
        "password": "Str0ng-Pass-123!", "password_confirm": "Str0ng-Pass-123!"}


class CompanySignupTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_creates_company_trial_plan_and_company_admin(self):
        r = self.client.post("/api/auth/register-company/", GOOD, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        u = User.objects.get(email="gina@globex.test")
        self.assertEqual(u.role, "company_admin")
        self.assertEqual(u.company.name, "Globex Ltd")
        self.assertEqual(u.company.status, "trial")
        self.assertEqual((u.company.plan.name, u.company.daily_limit), ("Trial", 100))   # never unlimited
        self.assertTrue(AuditLog.objects.filter(action="company.registered", company=u.company).exists())
        self.assertEqual(r.data["user"]["role"], "company_admin")
        # the new admin can use /company but not /platform
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(self.client.get("/api/company/overview/").status_code, 200)
        self.assertEqual(self.client.get("/api/platform/overview/").status_code, 403)

    def test_request_cannot_choose_role_plan_quota_or_company(self):
        other = Company.objects.create(name="Victim Co")
        body = {**GOOD, "role": "super_admin", "plan": 1, "daily_quota": 10**6, "company": other.id, "is_superuser": True, "is_staff": True}
        r = self.client.post("/api/auth/register-company/", body, format="json")
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(email="gina@globex.test")
        self.assertEqual(u.role, "company_admin")
        self.assertNotEqual(u.company_id, other.id)
        self.assertFalse(u.is_superuser or u.is_staff)
        self.assertIsNone(u.daily_quota)   # per-user quota fields untouched; company limit (100) applies

    def test_validation_errors(self):
        Company.objects.create(name="globex ltd")
        r = self.client.post("/api/auth/register-company/", GOOD, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("company_name", r.data["detail"])
        User.objects.create_user("e", "gina@globex.test", "x")
        r = self.client.post("/api/auth/register-company/", {**GOOD, "company_name": "Fresh"}, format="json")
        self.assertIn("email", r.data["detail"])
        r = self.client.post("/api/auth/register-company/", {**GOOD, "company_name": "F2", "email": "n@x.test", "password": "123", "password_confirm": "123"}, format="json")
        self.assertIn("password", r.data["detail"])
        r = self.client.post("/api/auth/register-company/", {**GOOD, "company_name": "F3", "email": "m@x.test", "password_confirm": "different"}, format="json")
        self.assertIn("password_confirm", r.data["detail"])
        self.assertFalse(Company.objects.filter(name__in=["Fresh", "F2", "F3"]).exists())   # nothing half-created

    @override_settings(ALLOW_COMPANY_SIGNUP=False)
    def test_can_be_disabled(self):
        self.assertEqual(self.client.post("/api/auth/register-company/", GOOD, format="json").status_code, 403)

    def test_archived_trial_plan_blocks_signup_instead_of_creating_unlimited_company(self):
        from .models import Plan
        Plan.objects.create(name="Trial", daily_quota=1, monthly_quota=1, max_users=1, is_active=False)
        self.assertEqual(self.client.post("/api/auth/register-company/", GOOD, format="json").status_code, 503)
        self.assertFalse(Company.objects.filter(name="Globex Ltd").exists())

    def test_no_self_promotion_paths(self):
        cache.clear()
        r = self.client.post("/api/auth/register/", {"username": "sneaky", "email": "s@x.test", "password": "Str0ng-Pass-123!",
                                                     "password_confirm": "Str0ng-Pass-123!", "role": "super_admin", "company": 1}, format="json")
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(username="sneaky")
        self.assertEqual((u.role, u.company_id), ("user", None))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.client.patch("/api/auth/me/", {"role": "super_admin", "company": 1, "daily_quota": None}, format="json")
        u.refresh_from_db()
        self.assertEqual((u.role, u.company_id), ("user", None))
        self.assertEqual(self.client.get("/api/platform/overview/").status_code, 403)
        self.assertEqual(self.client.get("/api/company/overview/").status_code, 403)


class JoinCompanyTests(TenantBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.plan.max_users = 10; self.plan.save()
        self.login(self.acme_admin)
        r = self.client.post("/api/company/members/", {"email": "newbie@acme.test", "role": "user"}, format="json")
        self.token = r.data["invite_url"].split("token=")[1]
        self.client.force_authenticate(user=None)

    def test_invite_info_shows_company_and_never_a_password_hash(self):
        r = self.client.get("/api/auth/invite-info/", {"token": self.token})
        self.assertEqual((r.status_code, r.data["company"], r.data["email"], r.data["role"]), (200, self.acme.name, "newbie@acme.test", "user"))
        self.assertNotIn("password", str(r.data).lower().replace("first_time", ""))
        self.assertEqual(self.client.get("/api/auth/invite-info/", {"token": "nope"}).status_code, 400)

    def test_join_assigns_company_and_user_role_ignoring_tampering(self):
        body = {"token": self.token, "password": "Str0ng-Pass-123!", "email": "NEWBIE@acme.test", "first_name": "New", "last_name": "Bie",
                "role": "super_admin", "company": self.beta.id}
        self.assertEqual(self.client.post("/api/auth/accept-invite/", body, format="json").status_code, 200)
        u = User.objects.get(email="newbie@acme.test")
        self.assertEqual((u.role, u.company_id, u.first_name), ("user", self.acme.id, "New"))
        login = self.client.post("/api/auth/login/", {"username": "newbie@acme.test", "password": "Str0ng-Pass-123!"}, format="json")
        self.assertEqual((login.status_code, login.data["user"]["role"]), (200, "user"))
        self.assertEqual(self.client.get("/api/auth/invite-info/", {"token": self.token}).status_code, 400)   # single use

    def test_wrong_email_is_refused_and_does_not_consume_the_link(self):
        r = self.client.post("/api/auth/accept-invite/", {"token": self.token, "password": "Str0ng-Pass-123!", "email": "other@x.test"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.get(email="newbie@acme.test").has_usable_password())
        self.assertEqual(self.client.get("/api/auth/invite-info/", {"token": self.token}).status_code, 200)

    def test_login_returns_verified_role_for_each_persona(self):
        for who, role in ((self.acme_admin, "company_admin"), (self.acme_user, "user"), (self.root, "super_admin")):
            who.set_password("Str0ng-Pass-123!"); who.save()
            r = self.client.post("/api/auth/login/", {"username": who.email, "password": "Str0ng-Pass-123!"}, format="json")
            self.assertEqual(r.data["user"]["role"], role)


class ProviderChoiceTests(Fixture, APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = self.make_user("chooser")
        self.company = Company.objects.create(name="Chooser Co", allowed_providers=["brevo", "smtp"], preferred_provider="brevo")
        self.owner.company = self.company; self.owner.save()
        self.client.force_authenticate(self.owner)
        self.ps = PlatformSettings.load()

    def _enable_choice(self, on=True):
        self.ps.allow_company_provider_choice = on; self.ps.save()

    def test_options_endpoint_follows_policy_and_exposes_no_secrets(self):
        r = self.client.get("/api/campaigns/providers/")
        self.assertEqual([o["name"] for o in r.data["options"]], ["brevo", "smtp"])        # both are always listed
        self.assertEqual({o["name"]: o["allowed"] for o in r.data["options"]}, {"brevo": True, "smtp": False})   # choice off
        self.assertIn("administrator", [o for o in r.data["options"] if o["name"] == "smtp"][0]["reason"])
        self.assertFalse(r.data["choice_allowed"])
        self._enable_choice()
        r = self.client.get("/api/campaigns/providers/")
        self.assertEqual({o["name"]: o["allowed"] for o in r.data["options"]}, {"brevo": True, "smtp": True})
        self.assertTrue(r.data["choice_allowed"])
        smtp = [o for o in r.data["options"] if o["name"] == "smtp"][0]
        self.assertFalse(smtp["usable"])                                   # SMTP env is not configured in tests
        self.assertEqual(smtp["reason"], "Not configured on the server yet.")
        self.assertEqual(set(r.data["options"][0]), {"name", "label", "allowed", "ready", "usable", "reason"})
        self.assertNotIn("password", str(r.data).lower())

    def test_cannot_request_a_provider_you_are_not_allowed(self):
        c = self.make_campaign(self.owner, n=1)
        r = self.client.patch(f"/api/campaigns/{c.id}/", {"requested_provider": "smtp"}, format="json")
        self.assertEqual(r.status_code, 400)       # company choice is off
        self._enable_choice()
        self.assertEqual(self.client.patch(f"/api/campaigns/{c.id}/", {"requested_provider": "smtp"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/campaigns/{c.id}/", {"requested_provider": "carrier-pigeon"}, format="json").status_code, 400)

    def test_requested_provider_is_frozen_at_start_and_used_for_sending(self):
        self._enable_choice()
        c = self.make_campaign(self.owner, n=1)
        Campaign.objects.filter(pk=c.pk).update(requested_provider="smtp")
        fake = MagicMock(); fake.send.return_value = SendResult(provider="smtp", message_id="<m@x>", raw={})
        with patch("providers.smtp_provider.SmtpProvider.validate_config", return_value=None), \
             patch("providers.dispatch.get_provider", return_value=fake) as gp:
            done = send_campaign_now(Campaign.objects.get(pk=c.pk))
        self.assertEqual(done.provider, "smtp")
        self.assertIn("smtp", [call.args[0] for call in gp.call_args_list])
        self.assertTrue(fake.send.called)

    def test_choice_revoked_before_start_is_refused_not_silently_switched(self):
        self._enable_choice()
        c = self.make_campaign(self.owner, n=1)
        Campaign.objects.filter(pk=c.pk).update(requested_provider="smtp")
        self._enable_choice(False)
        with self.assertRaises(ValidationAppError):
            _claim_campaign_for_sending(c.id)
        self.assertEqual(Campaign.objects.get(pk=c.pk).provider, "")

    def test_unconfigured_provider_cannot_be_started(self):
        self._enable_choice()
        c = self.make_campaign(self.owner, n=1)
        Campaign.objects.filter(pk=c.pk).update(requested_provider="smtp")
        with self.assertRaises(ValidationAppError):       # SMTP env is not configured in tests
            _claim_campaign_for_sending(c.id)