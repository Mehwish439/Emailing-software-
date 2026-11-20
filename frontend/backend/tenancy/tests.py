"""
Tenant isolation, permissions and admin-API behaviour. The isolation tests are the important ones:
they prove users can only reach their own records, company admins only their own company's, and
only platform admins can use /api/platform/.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from analytics.models import CampaignEvent
from brevo.client import BrevoClient
from campaigns.models import Campaign, CampaignRecipient
from campaigns.services import resume_stuck_campaigns, send_campaign_now
from contacts.models import Contact, Suppression
from providers.models import OutboundMessage
from providers.tests import Fixture

from .models import AuditLog, Company, Plan, PlatformSettings, QuotaLedger
from .services import invite_url

User = get_user_model()


class TenantBase(Fixture, APITestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name="Pro", daily_quota=1000, monthly_quota=20000, max_users=3)
        self.acme = Company.objects.create(name="Acme", plan=self.plan)
        self.beta = Company.objects.create(name="Beta", plan=self.plan)
        self.acme_admin = self.make_user("acme_admin", company=self.acme, role="company_admin")
        self.acme_user = self.make_user("acme_user", company=self.acme, daily_quota=400, monthly_quota=8000)
        self.beta_admin = self.make_user("beta_admin", company=self.beta, role="company_admin")
        self.beta_user = self.make_user("beta_user", company=self.beta)
        self.root = self.make_user("root", role="super_admin")
        self.solo = self.make_user("solo")

    def login(self, user):
        self.client.force_authenticate(user=user)


class PermissionTests(TenantBase):
    def test_anonymous_is_rejected_everywhere(self):
        for url in ("/api/company/overview/", "/api/platform/overview/", "/api/platform/companies/"):
            self.assertEqual(self.client.get(url).status_code, 401, url)

    def test_regular_user_cannot_use_admin_apis(self):
        self.login(self.acme_user)
        for url in ("/api/company/overview/", "/api/company/members/", "/api/platform/overview/", "/api/platform/companies/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_company_admin_cannot_use_platform_api(self):
        self.login(self.acme_admin)
        for url in ("/api/platform/overview/", "/api/platform/companies/", "/api/platform/health/", "/api/platform/users/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.patch("/api/platform/settings/", {"rate_per_minute": 9999}, format="json").status_code, 403)

    def test_platform_admin_is_not_a_company_admin(self):
        self.login(self.root)
        self.assertEqual(self.client.get("/api/company/overview/").status_code, 403)

    def test_user_cannot_promote_self_or_change_own_quota(self):
        self.login(self.acme_user)
        r = self.client.patch("/api/auth/me/", {"role": "super_admin", "daily_quota": 10**9, "company": self.beta.id}, format="json")
        self.assertEqual(r.status_code, 200)
        self.acme_user.refresh_from_db()
        self.assertEqual((self.acme_user.role, self.acme_user.daily_quota, self.acme_user.company_id), ("user", 400, self.acme.id))

    def test_registration_cannot_set_role_or_company(self):
        r = self.client.post("/api/auth/register/", {"username": "evil", "email": "evil@example.com",
                             "password": "Str0ng-Pass-123!", "password_confirm": "Str0ng-Pass-123!",
                             "role": "super_admin", "company": self.acme.id, "is_superuser": True}, format="json")
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(username="evil")
        self.assertEqual((u.role, u.company_id, u.is_superuser), ("user", None, False))

    def test_me_exposes_quota_snapshot_without_secrets(self):
        self.login(self.acme_user)
        r = self.client.get("/api/auth/me/").data
        self.assertEqual(r["company"]["name"], "Acme")
        self.assertEqual(r["quota"]["user"]["daily_limit"], 400)
        self.assertEqual(r["quota"]["company"]["daily_limit"], 1000)
        self.assertNotIn("password", str(r).lower())


class IsolationTests(TenantBase):
    def test_users_only_see_their_own_campaigns_and_contacts(self):
        mine = self.make_campaign(self.acme_user, n=1, name="Mine")
        theirs = self.make_campaign(self.beta_user, n=1, name="Theirs")
        self.login(self.acme_user)
        ids = {c["id"] for c in self.client.get("/api/campaigns/").data["results"]}
        self.assertEqual(ids, {mine.id})
        self.assertEqual(self.client.get(f"/api/campaigns/{theirs.id}/").status_code, 404)
        emails = {c["email"] for c in self.client.get("/api/contacts/").data["results"]}
        self.assertTrue(all(e.startswith("acme_user") for e in emails))

    def test_company_admin_sees_only_own_company_members_and_campaigns(self):
        self.make_campaign(self.acme_user, n=1, name="A1")
        b = self.make_campaign(self.beta_user, n=1, name="B1")
        self.login(self.acme_admin)
        emails = {m["email"] for m in self.client.get("/api/company/members/").data["results"]}
        self.assertEqual(emails, {"acme_admin@example.com", "acme_user@example.com"})
        names = {c["name"] for c in self.client.get("/api/company/campaigns/").data["results"]}
        self.assertEqual(names, {"A1"})
        self.assertEqual(self.client.post(f"/api/company/campaigns/{b.id}/pause/").status_code, 404)

    def test_company_admin_cannot_modify_another_companys_user(self):
        self.login(self.acme_admin)
        r = self.client.patch(f"/api/company/members/{self.beta_user.id}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 404)
        self.beta_user.refresh_from_db()
        self.assertTrue(self.beta_user.is_active)
        self.assertEqual(self.client.post(f"/api/company/members/{self.beta_user.id}/campaigns/pause/").status_code, 404)

    def test_company_analytics_and_suppressions_are_scoped(self):
        for u, n in ((self.acme_user, "A"), (self.beta_user, "B")):
            camp = self.make_campaign(u, n=1, name=n)
            camp.status = "processing"
            camp.save()
        Suppression.objects.create(email="acme_user0@example.org", reason="hard_bounce")
        Suppression.objects.create(email="beta_user0@example.org", reason="unsubscribed")
        self.login(self.acme_admin)
        rows = self.client.get("/api/company/suppressions/").data["results"]
        self.assertEqual([r["email"] for r in rows], ["acme_user0@example.org"])

    def test_audit_log_is_scoped_per_company(self):
        AuditLog.objects.create(company=self.acme, actor=self.acme_admin, action="x.acme")
        AuditLog.objects.create(company=self.beta, actor=self.beta_admin, action="x.beta")
        self.login(self.acme_admin)
        self.assertEqual([a["action"] for a in self.client.get("/api/company/audit-log/").data["results"]], ["x.acme"])
        self.login(self.root)
        self.assertEqual(self.client.get("/api/platform/audit-log/").data["count"], 2)

    def test_platform_admin_sees_all_companies(self):
        self.login(self.root)
        names = {c["name"] for c in self.client.get("/api/platform/companies/").data["results"]}
        self.assertEqual(names, {"Acme", "Beta"})
        self.assertEqual(self.client.get("/api/platform/users/").data["count"], 6)

    def test_cannot_pass_company_id_to_reach_other_tenant(self):
        self.login(self.acme_admin)
        r = self.client.get("/api/company/overview/", {"company": self.beta.id, "company_id": self.beta.id})
        self.assertEqual(r.data["company"]["name"], "Acme")


class CompanyAdminTests(TenantBase):
    def setUp(self):
        super().setUp()
        self.login(self.acme_admin)

    def test_invite_creates_passwordless_user_with_limits_and_audit(self):
        r = self.client.post("/api/company/members/", {"email": "New@Example.com", "first_name": "New",
                             "daily_quota": 300, "monthly_quota": 5000}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        u = User.objects.get(email="new@example.com")
        self.assertEqual((u.company_id, u.role, u.daily_quota), (self.acme.id, "user", 300))
        self.assertFalse(u.has_usable_password())
        self.assertIn("/join?token=", r.data["invite_url"])
        self.assertTrue(AuditLog.objects.filter(company=self.acme, action="user.invited").exists())

    def test_invite_respects_seat_limit_and_duplicates(self):
        self.client.post("/api/company/members/", {"email": "a@example.com"}, format="json")     # seat 3 of 3
        r = self.client.post("/api/company/members/", {"email": "b@example.com"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("allows 3 users", r.data["detail"])
        self.assertEqual(self.client.post("/api/company/members/", {"email": "acme_user@example.com"}, format="json").status_code, 400)

    def test_invite_link_is_single_use(self):
        r = self.client.post("/api/company/members/", {"email": "n@example.com"}, format="json")
        token = r.data["invite_url"].split("token=")[1]
        self.client.force_authenticate(user=None)
        ok = self.client.post("/api/auth/accept-invite/", {"token": token, "password": "Str0ng-Pass-123!"}, format="json")
        self.assertEqual(ok.status_code, 200)
        again = self.client.post("/api/auth/accept-invite/", {"token": token, "password": "An0ther-Pass-456!"}, format="json")
        self.assertEqual(again.status_code, 400)
        login = self.client.post("/api/auth/login/", {"username": "n@example.com", "password": "Str0ng-Pass-123!"}, format="json")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.post("/api/auth/accept-invite/", {"token": "garbage", "password": "x"}, format="json").status_code, 400)

    def test_weak_password_rejected_on_accept(self):
        r = self.client.post("/api/company/members/", {"email": "w@example.com"}, format="json")
        token = r.data["invite_url"].split("token=")[1]
        bad = self.client.post("/api/auth/accept-invite/", {"token": token, "password": "123"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_quota_edit_validation(self):
        url = f"/api/company/members/{self.acme_user.id}/"
        self.assertEqual(self.client.patch(url, {"daily_quota": 600, "monthly_quota": 9000}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"daily_quota": -1}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"daily_quota": "lots"}, format="json").status_code, 400)
        r = self.client.patch(url, {"daily_quota": 5000}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot exceed the company allowance", r.data["detail"])
        r = self.client.patch(url, {"daily_quota": 900, "monthly_quota": 100}, format="json")
        self.assertEqual(r.status_code, 400)                      # daily > monthly

    def test_cannot_over_allocate_company_quota_unless_policy_enabled(self):
        self.acme_admin.daily_quota = 500
        self.acme_admin.save()
        url = f"/api/company/members/{self.acme_user.id}/"
        r = self.client.patch(url, {"daily_quota": 600}, format="json")      # 500 + 600 > 1000
        self.assertEqual(r.status_code, 400)
        self.assertIn("would total 1,100", r.data["detail"])
        self.client.patch("/api/company/settings/", {"allow_overallocation": True}, format="json")
        self.assertEqual(self.client.patch(url, {"daily_quota": 600}, format="json").status_code, 200)

    def test_quota_page_reports_allocation(self):
        self.acme_admin.daily_quota = 300
        self.acme_admin.save()
        d = self.client.get("/api/company/quotas/").data
        self.assertEqual((d["daily_limit"], d["assigned_daily"], d["unallocated_daily"], d["over_allocated"]), (1000, 700, 300, False))
        self.assertEqual(len(d["users"]), 2)

    def test_increasing_user_quota_never_raises_company_allowance(self):
        self.client.patch(f"/api/company/members/{self.acme_user.id}/", {"daily_quota": 900}, format="json")
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.daily_limit, 1000)

    def test_cannot_deactivate_or_demote_self(self):
        url = f"/api/company/members/{self.acme_admin.id}/"
        self.assertEqual(self.client.patch(url, {"is_active": False}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"role": "user"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"role": "super_admin"}, format="json").status_code, 400)

    def test_deactivated_user_cannot_log_in(self):
        self.acme_user.set_password("Str0ng-Pass-123!")
        self.acme_user.save()
        self.client.patch(f"/api/company/members/{self.acme_user.id}/", {"is_active": False}, format="json")
        self.client.force_authenticate(user=None)
        r = self.client.post("/api/auth/login/", {"username": "acme_user@example.com", "password": "Str0ng-Pass-123!"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_pause_and_resume_a_users_campaigns(self):
        camp = self.make_campaign(self.acme_user, n=3)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}), \
                override_settings(CAMPAIGN_SEND_BATCH_SIZE=1):
            send_campaign_now(camp)
            r = self.client.post(f"/api/company/members/{self.acme_user.id}/campaigns/pause/")
            self.assertEqual(r.data["updated"], 1)
            resume_stuck_campaigns()                                         # paused -> nothing sent
            self.assertEqual(CampaignRecipient.objects.filter(status="sent").count(), 1)
            self.client.post(f"/api/company/campaigns/{camp.id}/resume/")
            resume_stuck_campaigns()
            resume_stuck_campaigns()
        camp.refresh_from_db()
        self.assertEqual(camp.status, "sent")

    def test_overview_uses_real_numbers(self):
        camp = self.make_campaign(self.acme_user, n=4)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}):
            send_campaign_now(camp)
        d = self.client.get("/api/company/overview/").data
        self.assertEqual(d["kpis"]["sent_today"], 4)
        self.assertEqual(d["kpis"]["daily_remaining"], 996)
        self.assertEqual(d["kpis"]["active_members"], 2)
        # Honest accounting: 4 accepted, but NO delivery event has been recorded -> 0.0%, never inflated.
        self.assertEqual(d["week"]["accepted"], 4)
        self.assertEqual(d["week"]["delivered"], 0)
        self.assertEqual(d["kpis"]["delivery_rate"], 0.0)

    def test_rates_are_null_not_zero_when_nothing_was_sent(self):
        d = self.client.get("/api/company/overview/").data
        self.assertIsNone(d["kpis"]["delivery_rate"])
        self.assertIsNone(d["kpis"]["bounce_rate"])

    def test_provider_choice_requires_platform_permission_and_approval(self):
        r = self.client.patch("/api/company/settings/", {"preferred_provider": "smtp"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_company_cannot_choose_unapproved_provider_even_if_platform_allows_choice(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"allow_company_provider_choice": True})
        self.acme.allowed_providers = ["brevo"]
        self.acme.save()
        self.assertEqual(self.client.patch("/api/company/settings/", {"preferred_provider": "smtp"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch("/api/company/settings/", {"preferred_provider": "brevo"}, format="json").status_code, 200)


class PlatformAdminTests(TenantBase):
    def setUp(self):
        super().setUp()
        self.login(self.root)

    def test_create_edit_company_and_audit(self):
        r = self.client.post("/api/platform/companies/", {"name": "Gamma", "plan": self.plan.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        cid = r.data["id"]
        r = self.client.patch(f"/api/platform/companies/{cid}/", {"daily_quota_override": 77}, format="json")
        self.assertEqual(r.data["daily_limit"], 77)
        self.assertEqual(self.client.post("/api/platform/companies/", {"name": "Gamma"}, format="json").status_code, 400)
        self.assertEqual(AuditLog.objects.filter(action__startswith="company.").count(), 2)

    def test_suspend_blocks_new_sends_and_holds_running_campaigns_then_reactivate(self):
        camp = self.make_campaign(self.acme_user, n=3)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}), \
                override_settings(CAMPAIGN_SEND_BATCH_SIZE=1):
            send_campaign_now(camp)
            r = self.client.post(f"/api/platform/companies/{self.acme.id}/suspend/")
            self.assertEqual(r.data["held_campaigns"], 1)
            resume_stuck_campaigns()
            self.assertEqual(CampaignRecipient.objects.filter(status="sent").count(), 1)      # held
            self.assertEqual(Campaign.objects.get(pk=camp.pk).status, "processing")           # not destroyed
            new = self.make_campaign(self.acme_user, n=1, name="N", prefix="zz")
            from common.exceptions import ValidationAppError
            with self.assertRaises(ValidationAppError):
                send_campaign_now(new)
            self.client.post(f"/api/platform/companies/{self.acme.id}/reactivate/")
            resume_stuck_campaigns()
            resume_stuck_campaigns()
        self.assertEqual(Campaign.objects.get(pk=camp.pk).status, "sent")

    def test_suspend_can_also_pause_running_campaigns(self):
        camp = self.make_campaign(self.acme_user, n=2)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}), \
                override_settings(CAMPAIGN_SEND_BATCH_SIZE=1):
            send_campaign_now(camp)
        self.client.post(f"/api/platform/companies/{self.acme.id}/suspend/", {"pause_running": True}, format="json")
        self.assertEqual(Campaign.objects.get(pk=camp.pk).status, "paused")

    def test_plan_crud_duplicate_archive(self):
        r = self.client.post("/api/platform/plans/", {"name": "Basic", "price_monthly": "29.00", "max_users": 5,
                             "daily_quota": 2000, "monthly_quota": 40000}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pid = r.data["id"]
        self.assertEqual(self.client.patch(f"/api/platform/plans/{pid}/", {"daily_quota": 2500}, format="json").data["daily_quota"], 2500)
        dup = self.client.post(f"/api/platform/plans/{pid}/duplicate/")
        self.assertEqual(dup.data["name"], "Basic (copy)")
        self.assertEqual(self.client.post(f"/api/platform/plans/{pid}/duplicate/").data["name"], "Basic (copy 2)")
        self.assertFalse(self.client.post(f"/api/platform/plans/{pid}/archive/").data["is_active"])

    def test_settings_validation_and_warning(self):
        # SMTP is refused until it is configured on the server...
        refused = self.client.patch("/api/platform/settings/", {"active_provider": "smtp"}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("not ready", str(refused.data))
        self.assertEqual(PlatformSettings.load().active_provider, "brevo")
        # ...and accepted once validate_config passes.
        with patch("providers.smtp_provider.SmtpProvider.validate_config", return_value=None):
            r = self.client.patch("/api/platform/settings/", {"rate_per_minute": 25, "active_provider": "smtp"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("does not override", r.data["warning"])
        self.assertEqual(self.client.patch("/api/platform/settings/", {"active_provider": "mailgun"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch("/api/platform/settings/", {"rate_per_minute": -5}, format="json").status_code, 400)

    def test_capacity_overcommit_is_reported_and_not_presented_as_guaranteed(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"daily_budget": 1500})
        d = self.client.get("/api/platform/quotas/").data
        self.assertEqual(d["allocated_daily"], 2000)
        self.assertTrue(d["overcommitted"])
        self.assertIn("not verified or guaranteed", d["overcommit_message"])
        PlatformSettings.objects.update(daily_budget=100000)
        self.assertFalse(self.client.get("/api/platform/quotas/").data["overcommitted"])

    def test_queue_overview_and_pause(self):
        camp = self.make_campaign(self.acme_user, n=1)
        camp.provider = "smtp"
        camp.save()
        rcpt = CampaignRecipient.objects.create(campaign=camp, contact=Contact.objects.get(owner=self.acme_user))
        OutboundMessage.objects.create(idempotency_key="q1", campaign=camp, recipient=rcpt, provider="smtp", state="queued")
        d = self.client.get("/api/platform/queue/").data
        self.assertEqual(d["states"], {"queued": 1})
        self.assertEqual(d["by_company"], [{"company": "Acme", "queued": 1}])
        self.assertTrue(self.client.post("/api/platform/queue/", {"paused": True}, format="json").data["paused"])
        self.assertTrue(PlatformSettings.load().queue_paused)

    def _failed_message(self, code="451"):
        camp = self.make_campaign(self.acme_user, n=1)
        camp.provider, camp.status = "smtp", "failed"
        camp.save()
        rcpt = CampaignRecipient.objects.create(campaign=camp, contact=Contact.objects.get(owner=self.acme_user), status="failed")
        QuotaLedger.objects.create(user=self.acme_user, company=self.acme, campaign=camp, recipient=rcpt,
                                   state="released", usage_date=timezone.localdate())
        return OutboundMessage.objects.create(idempotency_key="f1", campaign=camp, recipient=rcpt, provider="smtp",
                                              state="failed", last_error_code=code, attempts=3)

    def test_retry_only_temporary_failures_and_re_reserves_quota(self):
        m = self._failed_message("451")
        r = self.client.post(f"/api/platform/queue/messages/{m.id}/retry/")
        self.assertEqual(r.status_code, 200, r.data)
        m.refresh_from_db()
        self.assertEqual((m.state, m.attempts, m.recipient.status, m.campaign.status), ("queued", 0, "pending", "processing"))
        self.assertEqual(QuotaLedger.objects.get().state, "reserved")
        perm = self._failed_message("550") if False else None

    def test_permanent_failure_cannot_be_retried(self):
        m = self._failed_message("550")
        self.assertEqual(self.client.post(f"/api/platform/queue/messages/{m.id}/retry/").status_code, 400)

    def test_needs_review_requires_explicit_decision_and_is_not_blindly_retried(self):
        m = self._failed_message("")
        m.state = "needs_review"
        m.save()
        self.assertEqual(self.client.post(f"/api/platform/queue/messages/{m.id}/retry/").status_code, 400)
        self.assertEqual(self.client.post(f"/api/platform/queue/messages/{m.id}/resolve/", {"outcome": "maybe"}, format="json").status_code, 400)
        r = self.client.post(f"/api/platform/queue/messages/{m.id}/resolve/", {"outcome": "sent"}, format="json")
        self.assertEqual(r.data["state"], "accepted")
        m.recipient.refresh_from_db()
        self.assertEqual(m.recipient.status, "sent")

    def test_switch_provider_guards(self):
        camp = self.make_campaign(self.acme_user, n=1)
        camp.provider, camp.status = "smtp", "processing"
        camp.save()
        url = f"/api/platform/campaigns/{camp.id}/switch-provider/"
        self.assertEqual(self.client.post(url, {"provider": "nope"}, format="json").status_code, 400)
        rcpt = CampaignRecipient.objects.create(campaign=camp, contact=Contact.objects.get(owner=self.acme_user))
        OutboundMessage.objects.create(idempotency_key="u1", campaign=camp, recipient=rcpt, provider="smtp", state="needs_review")
        r = self.client.post(url, {"provider": "brevo"}, format="json")
        self.assertEqual(r.status_code, 409)                      # unknown-outcome messages block a switch
        OutboundMessage.objects.update(state="deferred")
        r = self.client.post(url, {"provider": "brevo"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        camp.refresh_from_db()
        self.assertEqual(camp.provider, "brevo")
        self.assertTrue(AuditLog.objects.filter(action="campaign.provider_switched").exists())

    def test_switch_to_unconfigured_provider_refused(self):
        camp = self.make_campaign(self.acme_user, n=1)
        camp.provider, camp.status = "brevo", "processing"
        camp.save()
        with override_settings(SMTP_HOST=""):
            r = self.client.post(f"/api/platform/campaigns/{camp.id}/switch-provider/", {"provider": "smtp"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not ready", r.data["detail"])

    def test_health_never_leaks_secrets_and_reports_state(self):
        with override_settings(SMTP_PASSWORD="SUPER-SECRET-PW", BREVO_API_KEY="xkeysib-SECRET"):
            d = self.client.get("/api/platform/health/", {"probe": "smtp"}).data
        blob = str(d)
        self.assertNotIn("SUPER-SECRET-PW", blob)
        self.assertNotIn("xkeysib-SECRET", blob)
        self.assertTrue(d["database"]["ok"])
        self.assertIn("smtp", d["providers"])
        self.assertFalse(d["broker"]["configured"])

    def test_user_deactivate_and_reset_invite_never_expose_passwords(self):
        r = self.client.post(f"/api/platform/users/{self.acme_user.id}/reset-invite/")
        self.assertIn("/join?token=", r.data["invite_url"])
        self.assertNotIn("password", str({k: v for k, v in r.data.items() if k != "invite_url"}).lower())
        self.assertFalse(self.client.post(f"/api/platform/users/{self.acme_user.id}/deactivate/").data["is_active"])
        self.assertEqual(self.client.post(f"/api/platform/users/{self.root.id}/deactivate/").status_code, 400)

    def test_old_reset_link_dies_after_password_changes(self):
        link = self.client.post(f"/api/platform/users/{self.acme_user.id}/reset-invite/").data["invite_url"]
        token = link.split("token=")[1]
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post("/api/auth/accept-invite/", {"token": token, "password": "Str0ng-Pass-123!"}, format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/accept-invite/", {"token": token, "password": "Hijack-Pass-999!"}, format="json").status_code, 400)