"""
Tests for the provider layer, idempotent dispatch, quotas and fair rate limiting.

SMTP behaviour is exercised against a REAL local SMTP server (aiosmtpd) rather than mocks, so
connection, auth, response-code and dropped-connection handling is genuinely executed.
No test touches a real mail server or a live mailing list.
"""
import socket
from datetime import timedelta
from unittest.mock import patch

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from brevo.client import BrevoClient
from campaigns.models import Campaign, CampaignRecipient
from campaigns.services import resume_stuck_campaigns, send_campaign_now
from common.exceptions import BrevoAPIError, ValidationAppError
from contacts.models import Contact, ContactList, Suppression
from email_templates.models import EmailTemplate
from tenancy import quota
from tenancy.models import Company, PlatformSettings, Plan, QuotaLedger

from . import dispatch, ratelimit
from .base import (
    BaseProvider, ProviderAmbiguousError, ProviderConfigError, ProviderPermanentError,
    ProviderTemporaryError, SendResult,
)
from .brevo_provider import BrevoProvider
from .dispatch import Outcome
from .models import OutboundMessage
from .smtp_provider import SmtpProvider, parse_verp, verp_return_path

User = get_user_model()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Recorder:
    """aiosmtpd handler: records messages; behaviour is scripted per test."""

    def __init__(self, rcpt="250 OK", data="250 OK queued as ABC123", drop_after_data=False):
        self.messages, self.rcpt, self.data, self.drop = [], rcpt, data, drop_after_data

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if not self.rcpt.startswith("250"):
            return self.rcpt
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        if self.drop:
            server.transport.abort()  # connection dies before the final reply is sent
            return "250 OK"
        return self.data


def smtp_server(handler=None, auth=None):
    handler = handler or Recorder()
    port = free_port()
    kwargs = {}
    if auth:
        kwargs = {"authenticator": auth, "auth_required": True, "auth_require_tls": False}
    controller = Controller(handler, hostname="127.0.0.1", port=port, **kwargs)
    controller.start()
    return controller, handler, port


def smtp_settings(port, **extra):
    base = dict(SMTP_HOST="127.0.0.1", SMTP_PORT=port, SMTP_USE_TLS=False, SMTP_USE_SSL=False,
                SMTP_USERNAME="", SMTP_PASSWORD="", SMTP_FROM_EMAIL="news@example.com", SMTP_TIMEOUT=5)
    base.update(extra)
    return override_settings(**base)


class Fixture:
    """Shared builders."""

    def make_user(self, name="owner", **kw):
        return User.objects.create_user(username=name, email=f"{name}@example.com", password="x-pass-12345", **kw)

    def make_campaign(self, user, n=3, name="Camp", prefix=None):
        tpl = EmailTemplate.objects.create(name=f"T-{name}", subject="Hi {{first_name}}",
                                           html_content="<p>Hello {{first_name}} {{unsubscribe_url}}</p>", created_by=user)
        lst = ContactList.objects.create(owner=user, name=f"L-{name}")
        prefix = prefix or user.username
        for i in range(n):
            c = Contact.objects.create(owner=user, email=f"{prefix}{i}@example.org", first_name=f"N{i}")
            c.lists.add(lst)
        camp = Campaign.objects.create(name=name, subject="Hi {{first_name}}", sender_name="Sender",
                                       sender_email="news@example.com", template=tpl, created_by=user)
        camp.contact_lists.add(lst)
        return camp


# --------------------------------------------------------------------------- SMTP provider
class SmtpProviderTests(Fixture, TestCase):
    def _email(self, to="rcpt@example.org", key="k1"):
        from .base import OutboundEmail
        return OutboundEmail("Sender", "news@example.com", to, "R", "Subject", "<p>Body</p>",
                             headers={"X-Campaign-Id": "7", "List-Unsubscribe": "<https://x/u>"}, idempotency_key=key)

    def test_successful_send_delivers_message_with_headers_and_ids(self):
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        with smtp_settings(port):
            res = SmtpProvider().send(self._email())
        self.assertEqual(res.provider, "smtp")
        self.assertTrue(res.message_id.startswith("<"))
        self.assertEqual(res.queue_id, "ABC123")
        self.assertEqual(len(rec.messages), 1)
        body = rec.messages[0].content.decode()
        self.assertIn("X-Campaign-Id: 7", body)
        self.assertIn("List-Unsubscribe:", body)
        self.assertIn("Message-ID: " + res.message_id, body)

    def test_very_long_html_line_is_accepted(self):
        """Regression: minified marketing HTML is one huge line; 7bit encoding was rejected (RFC 998 limit)."""
        from .base import OutboundEmail
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        html = "<p>" + ("lorem ipsum dolor sit amet " * 400) + "</p>"          # ~10,800 chars, no newline
        email = OutboundEmail("S", "news@example.com", "r@example.org", "R", "Subj \u00e9\u00e8 caf\u00e9", html,
                              idempotency_key="long")
        with smtp_settings(port):
            SmtpProvider().send(email)
        raw = rec.messages[0].content.decode()
        self.assertTrue(all(len(line) <= 998 for line in raw.splitlines()))
        self.assertIn("quoted-printable", raw)

    def test_list_unsubscribe_header_is_plain_not_rfc2047_encoded(self):
        """Regression: a long <https://...> header was emitted as =?utf-8?q?...?=, which breaks one-click unsubscribe."""
        import email
        from .base import OutboundEmail
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        url = "https://api.example.com/api/unsubscribe/" + ("A" * 180) + "/"
        email_obj = OutboundEmail("S", "news@example.com", "r@example.org", "R", "Subj", "<p>x</p>",
                                  headers={"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
                                  idempotency_key="lu")
        with smtp_settings(port):
            SmtpProvider().send(email_obj)
        raw = rec.messages[0].content
        parsed = email.message_from_bytes(raw)
        self.assertEqual(parsed["List-Unsubscribe"].replace("\r\n", "").replace("\n", "").replace(" ", ""), f"<{url}>")
        self.assertNotIn(b"=?utf-8?", raw.split(b"\r\n\r\n")[0].lower())

    def test_message_id_is_deterministic_for_same_idempotency_key(self):
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        with smtp_settings(port):
            a = SmtpProvider().send(self._email(key="same")).message_id
            b = SmtpProvider().send(self._email(key="same")).message_id
        self.assertEqual(a, b)

    def test_bad_credentials_give_clear_config_error(self):
        def auth(server, session, envelope, mechanism, data):
            ok = isinstance(data, LoginPassword) and data.login == b"u" and data.password == b"right"
            return AuthResult(success=ok, handled=False)  # handled=False -> server sends 235/535 itself
        ctrl, rec, port = smtp_server(auth=auth)
        self.addCleanup(ctrl.stop)
        with smtp_settings(port, SMTP_USERNAME="u", SMTP_PASSWORD="wrong"):
            with self.assertRaisesRegex(ProviderConfigError, "authentication failed"):
                SmtpProvider().send(self._email())
        self.assertEqual(rec.messages, [])
        with smtp_settings(port, SMTP_USERNAME="u", SMTP_PASSWORD="right"):
            SmtpProvider().send(self._email())
        self.assertEqual(len(rec.messages), 1)

    def test_conflicting_tls_modes_and_missing_config_rejected(self):
        with smtp_settings(587, SMTP_USE_TLS=True, SMTP_USE_SSL=True):
            with self.assertRaisesRegex(ProviderConfigError, "mutually exclusive"):
                SmtpProvider().validate_config()
        with smtp_settings(587, SMTP_HOST=""):
            with self.assertRaisesRegex(ProviderConfigError, "SMTP_HOST"):
                SmtpProvider().validate_config()
        with smtp_settings(587, SMTP_USERNAME="u", SMTP_PASSWORD=""):
            with self.assertRaisesRegex(ProviderConfigError, "together"):
                SmtpProvider().validate_config()

    def test_5xx_recipient_is_permanent_4xx_is_temporary(self):
        ctrl, rec, port = smtp_server(Recorder(rcpt="550 no such user"))
        self.addCleanup(ctrl.stop)
        with smtp_settings(port), self.assertRaises(ProviderPermanentError):
            SmtpProvider().send(self._email())
        ctrl2, rec2, port2 = smtp_server(Recorder(rcpt="451 greylisted, try later"))
        self.addCleanup(ctrl2.stop)
        with smtp_settings(port2), self.assertRaises(ProviderTemporaryError):
            SmtpProvider().send(self._email())

    def test_data_4xx_is_temporary(self):
        ctrl, rec, port = smtp_server(Recorder(data="451 4.3.0 try again"))
        self.addCleanup(ctrl.stop)
        with smtp_settings(port), self.assertRaises(ProviderTemporaryError):
            SmtpProvider().send(self._email())

    def test_connection_refused_is_temporary_and_nothing_accepted(self):
        with smtp_settings(free_port()), self.assertRaises(ProviderTemporaryError):
            SmtpProvider().send(self._email())

    def test_connection_lost_after_body_sent_is_ambiguous_not_retryable(self):
        ctrl, rec, port = smtp_server(Recorder(drop_after_data=True))
        self.addCleanup(ctrl.stop)
        with smtp_settings(port), self.assertRaises(ProviderAmbiguousError):
            SmtpProvider().send(self._email())

    def test_health_reports_ok_and_down(self):
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        with smtp_settings(port):
            self.assertTrue(SmtpProvider().health()["ok"])
        with smtp_settings(free_port()):
            h = SmtpProvider().health()
        self.assertFalse(h["ok"])
        self.assertNotIn("password", str(h).lower())

    def test_verp_roundtrip_and_tamper_detection(self):
        with override_settings(SMTP_BOUNCE_DOMAIN="bounce.example.com"):
            addr = verp_return_path(recipient_id=42, campaign_id=7)
            self.assertEqual(parse_verp(addr), (7, 42))
            self.assertIsNone(parse_verp(addr.replace(".42.", ".43.")))
        self.assertIsNone(parse_verp("someone@example.com"))


# ----------------------------------------------------------------------- Brevo classification
class BrevoClassificationTests(TestCase):
    def test_taxonomy(self):
        import requests
        from .brevo_provider import classify_brevo_error as c
        self.assertIsInstance(c(BrevoAPIError("bad", status_code=400)), ProviderPermanentError)
        self.assertIsInstance(c(BrevoAPIError("slow", status_code=429)), ProviderTemporaryError)
        self.assertIsInstance(c(BrevoAPIError("down", status_code=503)), ProviderTemporaryError)
        self.assertIsInstance(c(BrevoAPIError("no key")), ProviderTemporaryError)
        self.assertIsInstance(c(BrevoAPIError("BREVO_API_KEY is not configured.")), ProviderConfigError)
        err = BrevoAPIError("timeout")
        err.__cause__ = requests.exceptions.ReadTimeout()
        self.assertIsInstance(c(err), ProviderAmbiguousError)
        err2 = BrevoAPIError("refused")
        err2.__cause__ = requests.exceptions.ConnectionError()
        self.assertIsInstance(c(err2), ProviderTemporaryError)


# ------------------------------------------------------------------------------- dispatch
class FakeProvider(BaseProvider):
    name = "smtp"

    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def validate_config(self):
        pass

    def send(self, email):
        self.calls += 1
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, Exception):
            raise step
        return SendResult(provider=self.name, message_id=f"<m{self.calls}@x>", queue_id="Q1")


class DispatchTests(Fixture, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.camp = self.make_campaign(self.user, n=1)
        self.camp.provider = "smtp"
        self.camp.save()
        self.camp.status = Campaign.Status.PROCESSING
        self.camp.save()
        self.rcpt = CampaignRecipient.objects.create(campaign=self.camp, contact=Contact.objects.get())

    def run_send(self, provider):
        with patch("providers.dispatch.get_provider", return_value=provider):
            return dispatch.send_recipient(self.camp, self.rcpt)

    def test_accepted_message_is_never_sent_twice(self):
        p = FakeProvider([])
        self.assertEqual(self.run_send(p), Outcome.ACCEPTED)
        self.assertEqual(self.run_send(p), Outcome.ACCEPTED)
        self.assertEqual(self.run_send(p), Outcome.ACCEPTED)
        self.assertEqual(p.calls, 1)
        msg = OutboundMessage.objects.get()
        self.assertEqual((msg.provider, msg.provider_message_id, msg.provider_queue_id), ("smtp", "<m1@x>", "Q1"))
        self.assertEqual(msg.state, "accepted")
        self.assertEqual(OutboundMessage.objects.count(), 1)

    def test_ambiguous_result_goes_to_review_and_is_not_retried(self):
        p = FakeProvider([ProviderAmbiguousError("conn lost after DATA")])
        self.assertEqual(self.run_send(p), Outcome.REVIEW)
        self.assertEqual(self.run_send(p), Outcome.REVIEW)
        self.assertEqual(p.calls, 1)
        self.assertEqual(OutboundMessage.objects.get().state, "needs_review")

    def test_abandoned_submitting_claim_is_reviewed_not_resent(self):
        p = FakeProvider([])
        self.run_send(FakeProvider([ProviderTemporaryError("x")]))  # create row
        msg = OutboundMessage.objects.get()
        msg.state, msg.submitting_since = "submitting", timezone.now() - timedelta(minutes=30)
        msg.save()
        self.assertEqual(self.run_send(p), Outcome.REVIEW)
        self.assertEqual(p.calls, 0)

    def test_fresh_submitting_claim_means_another_worker_is_busy(self):
        self.run_send(FakeProvider([ProviderTemporaryError("x")]))
        msg = OutboundMessage.objects.get()
        msg.state, msg.submitting_since = "submitting", timezone.now()
        msg.save()
        p = FakeProvider([])
        self.assertEqual(self.run_send(p), Outcome.BUSY)
        self.assertEqual(p.calls, 0)

    @override_settings(SMTP_MAX_RETRIES=3)
    def test_smtp_temporary_failure_defers_with_backoff_then_retries_when_due(self):
        p = FakeProvider([ProviderTemporaryError("451 greylist"), "ok"])
        self.assertEqual(self.run_send(p), Outcome.DEFERRED)
        msg = OutboundMessage.objects.get()
        self.assertEqual((msg.state, msg.attempts), ("deferred", 1))
        self.assertGreater(msg.next_attempt_at, timezone.now())
        self.assertEqual(self.run_send(p), Outcome.DEFERRED)   # not due yet -> provider untouched
        self.assertEqual(p.calls, 1)
        msg.next_attempt_at = timezone.now() - timedelta(seconds=1)
        msg.save()
        self.assertEqual(self.run_send(p), Outcome.ACCEPTED)
        self.assertEqual(p.calls, 2)
        self.assertEqual(OutboundMessage.objects.get().attempts, 2)

    @override_settings(SMTP_MAX_RETRIES=2)
    def test_attempts_are_bounded(self):
        p = FakeProvider([ProviderTemporaryError("a"), ProviderTemporaryError("b"), ProviderTemporaryError("c")])
        self.assertEqual(self.run_send(p), Outcome.DEFERRED)
        OutboundMessage.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.run_send(p), Outcome.FAILED)
        self.assertEqual(p.calls, 2)
        self.assertEqual(self.run_send(p), Outcome.FAILED)
        self.assertEqual(p.calls, 2)

    def test_permanent_failure_is_not_retried(self):
        p = FakeProvider([ProviderPermanentError("550 no such user", code=550)])
        self.assertEqual(self.run_send(p), Outcome.FAILED)
        self.assertEqual(self.run_send(p), Outcome.FAILED)
        self.assertEqual(p.calls, 1)

    def test_config_error_sends_nothing_and_keeps_message_retryable(self):
        p = FakeProvider([ProviderConfigError("SMTP down config")])
        self.assertEqual(self.run_send(p), Outcome.CONFIG_ERROR)
        self.assertEqual(OutboundMessage.objects.get().state, "queued")
        self.assertEqual(self.run_send(FakeProvider([])), Outcome.ACCEPTED)

    def test_brevo_style_inline_retry_for_temporary_errors(self):
        self.camp.provider = "brevo"
        self.camp.save()
        p = FakeProvider([ProviderTemporaryError("blip"), "ok"])
        p.name = "brevo"
        self.assertEqual(self.run_send(p), Outcome.ACCEPTED)
        self.assertEqual(p.calls, 2)


# ------------------------------------------------------------------------ end-to-end campaigns
class CampaignProviderFlowTests(Fixture, TestCase):
    def setUp(self):
        self.user = self.make_user()

    def test_default_is_brevo_and_records_message_id(self):
        camp = self.make_campaign(self.user, n=2)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<b1@brevo>"}) as send:
            c = send_campaign_now(camp)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(c.status, Campaign.Status.SENT)
        self.assertEqual(c.provider, "brevo")
        self.assertEqual(set(OutboundMessage.objects.values_list("provider", "state")), {("brevo", "accepted")})
        self.assertEqual(OutboundMessage.objects.first().provider_message_id, "<b1@brevo>")

    def test_smtp_campaign_delivers_via_server_exactly_once_per_recipient(self):
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        camp = self.make_campaign(self.user, n=3)
        with smtp_settings(port), patch.object(BrevoClient, "send_transactional_email") as brevo:
            c = send_campaign_now(camp)
            resume_stuck_campaigns()      # duplicate cron ticks / resumes must not resend
            resume_stuck_campaigns()
        brevo.assert_not_called()
        self.assertEqual(c.status, Campaign.Status.SENT)
        self.assertEqual(c.provider, "smtp")
        self.assertEqual(len(rec.messages), 3)
        self.assertEqual(len({m.rcpt_tos[0] for m in rec.messages}), 3)
        self.assertEqual(OutboundMessage.objects.filter(state="accepted").count(), 3)

    def test_provider_is_frozen_when_platform_setting_changes_mid_campaign(self):
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        camp = self.make_campaign(self.user, n=3)
        with smtp_settings(port), override_settings(CAMPAIGN_SEND_BATCH_SIZE=1), \
                patch.object(BrevoClient, "send_transactional_email") as brevo:
            send_campaign_now(camp)                                   # first batch via SMTP
            PlatformSettings.objects.filter(pk=1).update(active_provider="brevo")   # admin flips it
            resume_stuck_campaigns()
            resume_stuck_campaigns()
        brevo.assert_not_called()
        self.assertEqual(len(rec.messages), 3)
        camp.refresh_from_db()
        self.assertEqual((camp.status, camp.provider), (Campaign.Status.SENT, "smtp"))

    def test_unconfigured_smtp_blocks_send_with_clear_error_and_reserves_nothing(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        camp = self.make_campaign(self.user, n=2)
        with smtp_settings(587, SMTP_HOST=""):
            with self.assertRaisesRegex(ValidationAppError, "not ready.*SMTP_HOST"):
                send_campaign_now(camp)
        camp.refresh_from_db()
        self.assertEqual((camp.status, camp.provider), (Campaign.Status.DRAFT, ""))
        self.assertEqual(QuotaLedger.objects.count(), 0)

    def test_server_outage_never_silently_fails_over_to_brevo(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        camp = self.make_campaign(self.user, n=2)
        with smtp_settings(free_port()), patch.object(BrevoClient, "send_transactional_email") as brevo:
            c = send_campaign_now(camp)
        brevo.assert_not_called()
        self.assertEqual(c.status, Campaign.Status.PROCESSING)      # held for retry, not failed
        self.assertEqual(CampaignRecipient.objects.filter(status="pending").count(), 2)
        self.assertEqual(set(OutboundMessage.objects.values_list("state", flat=True)), {"deferred"})

    def test_ambiguous_smtp_outcome_is_never_resent_on_resume(self):
        ctrl, rec, port = smtp_server(Recorder(drop_after_data=True))
        self.addCleanup(ctrl.stop)
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        camp = self.make_campaign(self.user, n=1)
        with smtp_settings(port):
            send_campaign_now(camp)
            resume_stuck_campaigns()
            resume_stuck_campaigns()
        self.assertEqual(len(rec.messages), 1)
        self.assertEqual(OutboundMessage.objects.get().state, "needs_review")
        self.assertEqual(QuotaLedger.objects.get().state, "consumed")   # conservative: may have been sent


# ---------------------------------------------------------------------------------- quotas
class QuotaTests(Fixture, TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name="Pro", daily_quota=100, monthly_quota=1000, max_users=10)
        self.company = Company.objects.create(name="Acme", plan=self.plan)
        self.user = self.make_user("sarah", company=self.company, daily_quota=50, monthly_quota=500)

    def send(self, camp):
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}):
            return send_campaign_now(camp)

    def test_credits_count_messages_not_campaigns(self):
        camp = self.make_campaign(self.user, n=7)
        self.send(camp)
        self.assertEqual(quota.usage(user=self.user)[0], 7)
        self.assertEqual(quota.usage(company=self.company)[0], 7)
        self.assertEqual(QuotaLedger.objects.filter(state="consumed").count(), 7)

    def test_user_limit_blocks_and_rolls_back_the_claim(self):
        camp = self.make_campaign(self.user, n=51)
        with self.assertRaisesRegex(ValidationAppError, "Daily user email quota exceeded.*needs 51.*only 50"):
            self.send(camp)
        camp.refresh_from_db()
        self.assertEqual(camp.status, Campaign.Status.DRAFT)
        self.assertEqual(QuotaLedger.objects.count(), 0)

    def test_company_limit_is_shared_between_users(self):
        other = self.make_user("ali", company=self.company, daily_quota=100, monthly_quota=1000)
        self.send(self.make_campaign(self.user, n=50, name="A"))
        self.send(self.make_campaign(other, n=40, name="B", prefix="ali"))      # company total now 90 of 100
        with self.assertRaisesRegex(ValidationAppError, "Daily company email quota exceeded"):
            self.send(self.make_campaign(other, n=11, name="C", prefix="zed"))

    def test_company_override_beats_plan(self):
        self.company.daily_quota_override = 5
        self.company.save()
        with self.assertRaisesRegex(ValidationAppError, "company email quota"):
            self.send(self.make_campaign(self.user, n=6))

    def test_platform_budget_applies_to_everyone(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"daily_budget": 10})
        solo = self.make_user("solo")          # legacy user: no company, no user limit
        with self.assertRaisesRegex(ValidationAppError, "Daily platform email quota exceeded"):
            self.send(self.make_campaign(solo, n=11, prefix="solo"))
        self.send(self.make_campaign(solo, n=10, name="ok", prefix="solo2"))

    def test_monthly_limit(self):
        self.user.monthly_quota = 5
        self.user.save()
        with self.assertRaisesRegex(ValidationAppError, "Monthly user"):
            self.send(self.make_campaign(self.user, n=6))

    def test_legacy_user_without_limits_is_unrestricted(self):
        solo = self.make_user("legacy")
        self.send(self.make_campaign(solo, n=25, prefix="legacy"))
        self.assertEqual(quota.usage(user=solo)[0], 25)

    def test_reservation_is_idempotent_no_double_charge(self):
        camp = self.make_campaign(self.user, n=5)
        from campaigns.services import build_recipient_snapshot
        build_recipient_snapshot(camp)
        camp.created_by = self.user
        self.assertEqual(quota.reserve_campaign_quota(camp), 5)
        self.assertEqual(quota.reserve_campaign_quota(camp), 0)
        self.assertEqual(QuotaLedger.objects.count(), 5)

    def test_late_suppression_releases_credit_and_retries_do_not_double_charge(self):
        camp = self.make_campaign(self.user, n=3)
        Suppression.objects.create(email="sarah1@example.org", reason="unsubscribed")
        # snapshot happens before suppression, so add it after snapshot:
        from campaigns.services import build_recipient_snapshot
        Suppression.objects.all().delete()
        build_recipient_snapshot(camp)
        Suppression.objects.create(email="sarah1@example.org", reason="unsubscribed")
        camp.status = Campaign.Status.SCHEDULED
        camp.save()
        self.send(camp)
        states = dict(QuotaLedger.objects.values_list("recipient__contact__email", "state"))
        self.assertEqual(states["sarah1@example.org"], "released")
        self.assertEqual(quota.usage(user=self.user)[0], 2)

    def test_failed_sends_release_credits(self):
        camp = self.make_campaign(self.user, n=2)
        with patch.object(BrevoClient, "send_transactional_email", side_effect=BrevoAPIError("bad", status_code=400)):
            c = send_campaign_now(camp)
        self.assertEqual(c.status, Campaign.Status.FAILED)
        self.assertEqual(quota.usage(user=self.user)[0], 0)
        self.assertEqual(set(QuotaLedger.objects.values_list("state", flat=True)), {"released"})

    def test_suspended_company_cannot_start_and_running_campaign_is_held(self):
        camp = self.make_campaign(self.user, n=3)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}), \
                override_settings(CAMPAIGN_SEND_BATCH_SIZE=1):
            send_campaign_now(camp)                              # 1 of 3 sent
            self.company.status = Company.Status.SUSPENDED
            self.company.save()
            resume_stuck_campaigns()                             # held: nothing more is sent
            camp.refresh_from_db()
            self.assertEqual(camp.status, Campaign.Status.PROCESSING)
            self.assertEqual(CampaignRecipient.objects.filter(status="sent").count(), 1)
            self.company.status = Company.Status.ACTIVE
            self.company.save()
            resume_stuck_campaigns()
            resume_stuck_campaigns()
        camp.refresh_from_db()
        self.assertEqual(camp.status, Campaign.Status.SENT)
        new = self.make_campaign(self.user, n=1, name="N", prefix="zz")
        self.company.status = Company.Status.SUSPENDED
        self.company.save()
        with self.assertRaisesRegex(ValidationAppError, "suspended"):
            self.send(new)

    def test_reconcile_repairs_drift(self):
        camp = self.make_campaign(self.user, n=2)
        self.send(camp)
        QuotaLedger.objects.update(state="reserved")             # simulate a crash after sending
        self.assertEqual(quota.reconcile()["consumed"], 2)
        self.assertEqual(set(QuotaLedger.objects.values_list("state", flat=True)), {"consumed"})


# ------------------------------------------------------------------- rate limit + fairness
class RateLimitTests(Fixture, TestCase):
    def _submit(self, camp, n):
        for i in range(n):
            contact = Contact.objects.filter(owner=camp.created_by).order_by("id")[i]
            rcpt, _ = CampaignRecipient.objects.get_or_create(campaign=camp, contact=contact)
            OutboundMessage.objects.create(idempotency_key=f"{camp.id}-{i}", campaign=camp, recipient=rcpt,
                                           provider="smtp", state="accepted", submitting_since=timezone.now())

    def _pending(self, camp):
        camp.provider, camp.status = "smtp", Campaign.Status.PROCESSING
        camp.save()
        for c in Contact.objects.filter(owner=camp.created_by):
            CampaignRecipient.objects.get_or_create(campaign=camp, contact=c)

    def test_unlimited_when_unset_and_blocked_when_paused(self):
        camp = self.make_campaign(self.make_user(), n=2)
        camp.provider = "smtp"
        self.assertTrue(ratelimit.may_submit(camp))
        PlatformSettings.objects.update_or_create(pk=1, defaults={"queue_paused": True})
        self.assertFalse(ratelimit.may_submit(camp))

    def test_global_rate_is_enforced(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"rate_per_minute": 4})
        u = self.make_user("a")
        camp = self.make_campaign(u, n=6)
        self._pending(camp)
        self.assertTrue(ratelimit.may_submit(camp))
        self._submit(camp, 4)
        self.assertFalse(ratelimit.may_submit(camp))

    def test_smtp_rate_env_default_used_when_platform_rate_unset(self):
        camp = self.make_campaign(self.make_user("e"), n=3)
        self._pending(camp)
        with override_settings(SMTP_RATE_LIMIT=2):
            self.assertTrue(ratelimit.may_submit(camp))
            self._submit(camp, 2)
            self.assertFalse(ratelimit.may_submit(camp))

    def test_one_company_cannot_monopolise_capacity(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"rate_per_minute": 10})
        ca, cb = Company.objects.create(name="A"), Company.objects.create(name="B")
        ua, ub = self.make_user("ua", company=ca), self.make_user("ub", company=cb)
        a, b = self.make_campaign(ua, n=12, name="A"), self.make_campaign(ub, n=12, name="B")
        self._pending(a)
        self._pending(b)                       # both companies have pending work -> share is 5 each
        self._submit(a, 5)
        self.assertFalse(ratelimit.may_submit(a), "A used its fair share while B is waiting")
        self.assertTrue(ratelimit.may_submit(b), "B's reserved share must stay available")

    def test_idle_capacity_can_be_borrowed(self):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"rate_per_minute": 10})
        ca, cb = Company.objects.create(name="A"), Company.objects.create(name="B")
        ua, ub = self.make_user("ua", company=ca), self.make_user("ub", company=cb)
        a = self.make_campaign(ua, n=12, name="A")
        self.make_campaign(ub, n=2, name="B")  # B exists but has nothing pending -> idle
        self._pending(a)
        self._submit(a, 9)
        self.assertTrue(ratelimit.may_submit(a), "A may borrow B's idle share up to the global rate")
        self._submit_extra = None


# ------------------------------------------------------------------------------ celery tasks
class TaskTests(Fixture, TestCase):
    """Tasks are exercised synchronously (calling the function), which is how Celery eager mode runs them."""

    def test_process_due_runs_and_records_heartbeat(self):
        from tenancy.models import JobHeartbeat
        from .tasks import process_due
        self.assertEqual(process_due(), 0)
        self.assertEqual(JobHeartbeat.objects.get(name="process_due").last_status, "ok")
        process_due()
        self.assertEqual(JobHeartbeat.objects.get(name="process_due").runs, 2)

    def test_process_due_resumes_an_in_flight_campaign(self):
        from .tasks import process_due
        u = self.make_user()
        camp = self.make_campaign(u, n=3)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<x>"}), \
                override_settings(CAMPAIGN_SEND_BATCH_SIZE=1):
            send_campaign_now(camp)
            process_due()
            process_due()
        camp.refresh_from_db()
        self.assertEqual(camp.status, Campaign.Status.SENT)
        self.assertEqual(OutboundMessage.objects.filter(state="accepted").count(), 3)

    def test_reconcile_and_review_stuck_tasks(self):
        from .tasks import reconcile_quota, review_stuck
        self.assertEqual(reconcile_quota(), {"consumed": 0, "released": 0})
        u = self.make_user()
        camp = self.make_campaign(u, n=1)
        rcpt = CampaignRecipient.objects.create(campaign=camp, contact=Contact.objects.get())
        OutboundMessage.objects.create(idempotency_key="s", campaign=camp, recipient=rcpt, provider="smtp",
                                       state="submitting", submitting_since=timezone.now() - timedelta(minutes=30))
        self.assertEqual(review_stuck(), 1)
        self.assertEqual(OutboundMessage.objects.get().state, "needs_review")

    def test_smtp_health_task_records_status(self):
        from tenancy.models import JobHeartbeat
        from .tasks import smtp_health
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        with smtp_settings(port):
            self.assertTrue(smtp_health())
        with smtp_settings(free_port()):
            self.assertFalse(smtp_health())
        self.assertEqual(JobHeartbeat.objects.get(name="smtp_health").last_status, "error")

    def test_celery_app_loads_and_registers_tasks(self):
        from config.celery import app
        app.autodiscover_tasks(["providers", "tenancy"], force=True)   # autodiscovery is lazy; force it for the test
        names = set(app.tasks.keys())
        for n in ("mailflow.process_due", "mailflow.reconcile_quota", "mailflow.smtp_health", "mailflow.review_stuck"):
            self.assertIn(n, names)


# ----------------------------------------------------------------------------------- test emails
class TestSendTests(Fixture, TestCase):
    def test_test_email_uses_brevo_by_default_and_smtp_when_selected(self):
        from .testsend import send_test_email
        u = self.make_user()
        camp = self.make_campaign(u, n=1)
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<t>"}) as brevo:
            send_test_email(camp, "me@example.org")
        brevo.assert_called_once()
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        with smtp_settings(port), patch.object(BrevoClient, "send_transactional_email") as brevo2:
            send_test_email(camp, "me@example.org")
        brevo2.assert_not_called()
        self.assertEqual(len(rec.messages), 1)
        raw = rec.messages[0].content.decode()
        self.assertIn("Subject: [TEST]", raw)
        self.assertEqual(OutboundMessage.objects.count(), 0)          # not a campaign message
        self.assertEqual(QuotaLedger.objects.count(), 0)              # uses no quota credit

    def test_smtp_test_failure_surfaces_as_clear_error_for_the_api(self):
        from .testsend import send_test_email
        u = self.make_user()
        camp = self.make_campaign(u, n=1)
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        with smtp_settings(free_port()), self.assertRaisesRegex(BrevoAPIError, "smtp test send failed"):
            send_test_email(camp, "me@example.org")
