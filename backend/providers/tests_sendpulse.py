"""
SendPulse integration tests.

HOW THESE TESTS WORK (read this before trusting them):
  * A REAL local HTTP server (stdlib http.server, bound to 127.0.0.1) implements the parts of the SendPulse
    API this integration uses, as documented at https://sendpulse.com/integrations/api. The production
    client code runs unmodified over real sockets: OAuth token flow, base64 payloads, timeouts, dropped
    connections, 401/429/4xx/5xx. This mirrors how the SMTP provider is tested against a real aiosmtpd server.
  * It is NOT SendPulse. It proves our handling of the documented contract and of failure modes; it cannot
    prove SendPulse accepts a particular sender/domain, that SMTP is activated on an account, or what the
    undocumented webhook `data` fields look like. Those need real credentials: see LiveSendPulseTests at the
    bottom, which skip unless SENDPULSE_LIVE_CLIENT_ID / SENDPULSE_LIVE_CLIENT_SECRET are exported.
  * Brevo is patched exactly as in providers/tests.py (no real Brevo traffic from the suite).
"""
import base64
import hashlib
import hmac
import json
import os
import threading
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from analytics.models import CampaignEvent
from brevo.client import BrevoClient
from campaigns.models import Campaign, CampaignRecipient
from campaigns.services import send_campaign_now
from common.exceptions import ValidationAppError
from contacts.models import Suppression
from tenancy.models import PlatformSettings
from tenancy import quota

from . import dispatch, ratelimit
from .base import (
    OutboundEmail, ProviderAmbiguousError, ProviderConfigError, ProviderPermanentError, ProviderTemporaryError,
)
from .dispatch import Outcome
from .models import OutboundMessage, ProviderCredential, ProviderEventLog
from .registry import available_providers, get_provider
from .sendpulse_client import reset_process_cache
from .sendpulse_provider import SendPulseProvider, build_email_object
from .sendpulse_webhooks import ingest_event, verify_signature
from .textify import html_to_text
from .tests import Fixture

ID, SECRET = "test-client-id-1234567890", "test-client-secret-abcdefghij"
WEBHOOK_SECRET = "whsec-test-0123456789"


# =============================================================================== fake SendPulse server
class FakeSendPulse:
    """Scriptable local server. `send_script` is a list consumed one entry per POST /smtp/emails:
       ("ok",) | ("status", code, body) | ("accept_then_status", code) | ("drop",) | ("accept_then_drop",)
       When the script is exhausted, requests succeed."""

    def __init__(self):
        self.tokens_issued = 0
        self.valid_tokens = set()
        self.token_lifetime = 3600
        self.requests = []          # (method, path, auth header, body)
        self.accepted = []          # email objects the "server" took responsibility for
        self.send_script = []
        self.senders = ["news@example.com"]
        self.email_info = {}        # message id -> dict for GET /smtp/emails/{id}
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _read(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                return json.loads(raw) if raw else {}

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self):
                tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
                return tok in outer.valid_tokens

            def do_POST(self):
                body = self._read()
                with outer.lock:
                    outer.requests.append(("POST", self.path, self.headers.get("Authorization"), body))
                if self.path == "/oauth/access_token":
                    if body.get("client_id") != ID or body.get("client_secret") != SECRET \
                            or body.get("grant_type") != "client_credentials":
                        return self._send(401, {"error": "invalid_client", "message": "Client authentication failed"})
                    with outer.lock:
                        outer.tokens_issued += 1
                        tok = f"tok-{outer.tokens_issued}"
                        outer.valid_tokens.add(tok)
                    return self._send(200, {"access_token": tok, "token_type": "Bearer", "expires_in": outer.token_lifetime})
                if not self._authed():
                    return self._send(401, {"message": "Unauthorized"})
                if self.path == "/smtp/emails":
                    step = outer.send_script.pop(0) if outer.send_script else ("ok",)
                    kind = step[0]
                    if kind == "drop":
                        self.connection.close()
                        return
                    if kind == "hang":          # request received, no answer within the client timeout
                        import time
                        time.sleep(step[1])
                        return
                    if kind in ("ok", "accept_then_status", "accept_then_drop"):
                        with outer.lock:
                            outer.accepted.append(body["email"])
                            mid = f"msg-{len(outer.accepted):04d}"
                    if kind == "ok":
                        return self._send(200, {"result": True, "id": mid})
                    if kind == "accept_then_status":
                        return self._send(step[1], {"message": "gateway error"})
                    if kind == "accept_then_drop":
                        self.connection.close()
                        return
                    if kind == "status":
                        return self._send(step[1], step[2])
                    if kind == "result_false":
                        return self._send(200, {"result": False, "message": "rejected"})
                self._send(404, {"message": "not found"})

            def do_GET(self):
                with outer.lock:
                    outer.requests.append(("GET", self.path, self.headers.get("Authorization"), None))
                if not self._authed():
                    return self._send(401, {"message": "Unauthorized"})
                if self.path == "/user/info":
                    return self._send(200, {"id": 1, "name": "Test Account"})
                if self.path == "/smtp/senders":
                    return self._send(200, outer.senders)
                if self.path == "/user/balance/detail":
                    return self._send(200, {"smtp": {"tariff_name": "SMTP Free", "end_date": "2027-01-01"}})
                if self.path.startswith("/smtp/emails/"):
                    mid = self.path.rsplit("/", 1)[1]
                    return self._send(200, outer.email_info.get(mid, {"id": mid, "smtp_answer_code": None}))
                self._send(404, {"message": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def sp_settings(fake, **extra):
    base = dict(SENDPULSE_API_BASE_URL=fake.url, SENDPULSE_CLIENT_ID=ID, SENDPULSE_CLIENT_SECRET=SECRET,
                SENDPULSE_WEBHOOK_SECRET=WEBHOOK_SECRET, SENDPULSE_MIN_SEND_INTERVAL_MS=0,
                SENDPULSE_HTTP_TIMEOUT=2, SENDPULSE_RETRY_BACKOFF_SECONDS=30, SENDPULSE_MAX_SEND_ATTEMPTS=3)
    base.update(extra)
    return override_settings(**base)


class SPBase(Fixture, TestCase):
    def setUp(self):
        reset_process_cache()
        self.fake = FakeSendPulse()
        self.addCleanup(self.fake.stop)
        ctx = sp_settings(self.fake)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.owner = self.make_user("owner")

    def email(self, to="rcpt@example.org"):
        return OutboundEmail("Sender", "news@example.com", to, "Rec", "Subject",
                             "<p>Hi <a href='https://x.test/u/1'>Unsubscribe</a></p>",
                             headers={"X-Campaign-Id": "1"}, idempotency_key="k")

    def sp_campaign(self, n=3, name="SP"):
        camp = self.make_campaign(self.owner, n=n, name=name)
        camp.requested_provider = "sendpulse"
        camp.save()
        return camp

    def allow_choice(self):
        p = PlatformSettings.load()
        p.allow_company_provider_choice = True
        p.save()


# =============================================================================== authentication / token
class AuthTests(SPBase):
    def test_token_requested_once_and_reused(self):
        for i in range(3):
            SendPulseProvider().send(self.email(f"a{i}@example.org"))
        self.assertEqual(self.fake.tokens_issued, 1)
        self.assertEqual(len(self.fake.accepted), 3)
        self.assertTrue(all(r[2] == "Bearer tok-1" for r in self.fake.requests if r[1] == "/smtp/emails"))

    def test_expired_token_is_refreshed(self):
        self.fake.token_lifetime = 1          # shorter than the refresh margin -> never reused
        SendPulseProvider().send(self.email("a@example.org"))
        SendPulseProvider().send(self.email("b@example.org"))
        self.assertEqual(self.fake.tokens_issued, 2)

    def test_revoked_token_gets_one_refresh_and_no_duplicate(self):
        SendPulseProvider().send(self.email("a@example.org"))
        self.fake.valid_tokens.clear()        # server revokes everything
        res = SendPulseProvider().send(self.email("b@example.org"))
        self.assertTrue(res.message_id)
        self.assertEqual(self.fake.tokens_issued, 2)
        self.assertEqual([e["to"][0]["email"] for e in self.fake.accepted], ["a@example.org", "b@example.org"])

    @override_settings(SENDPULSE_CLIENT_SECRET="wrong")
    def test_invalid_credentials_is_a_config_error_and_sends_nothing(self):
        with self.assertRaises(ProviderConfigError) as ctx:
            SendPulseProvider().send(self.email())
        self.assertNotIn("wrong", str(ctx.exception))
        self.assertEqual(self.fake.accepted, [])

    @override_settings(SENDPULSE_CLIENT_ID="", SENDPULSE_CLIENT_SECRET="")
    def test_unconfigured_fails_validate_config_without_network(self):
        with self.assertRaises(ProviderConfigError):
            SendPulseProvider().validate_config()
        self.assertEqual(self.fake.requests, [])

    def test_plain_http_to_a_remote_host_is_refused(self):
        with override_settings(SENDPULSE_API_BASE_URL="http://api.example.com"):
            with self.assertRaises(ProviderConfigError):
                SendPulseProvider().validate_config()

    def test_token_is_shared_through_the_database_across_processes(self):
        with override_settings(PROVIDER_CREDENTIALS_KEY=Fernet.generate_key().decode()):
            SendPulseProvider().send(self.email("a@example.org"))
            reset_process_cache()             # a different gunicorn worker: empty memory
            SendPulseProvider().send(self.email("b@example.org"))
            row = ProviderCredential.objects.get(provider="sendpulse")
            self.assertEqual(self.fake.tokens_issued, 1)
            self.assertNotIn("tok-1", row.encrypted_token)      # stored encrypted, never plaintext
            self.assertTrue(row.encrypted_token)


# =============================================================================== payload
class PayloadTests(SPBase):
    def test_payload_has_base64_html_text_sender_recipient_and_no_headers(self):
        SendPulseProvider().send(self.email())
        sent = self.fake.accepted[0]
        self.assertIn("Unsubscribe", base64.b64decode(sent["html"]).decode())
        self.assertIn("https://x.test/u/1", sent["text"])
        self.assertEqual(sent["subject"], "Subject")
        self.assertEqual(sent["from"], {"email": "news@example.com", "name": "Sender"})
        self.assertEqual(sent["to"], [{"email": "rcpt@example.org", "name": "Rec"}])
        self.assertNotIn("headers", sent)                       # the SMTP API accepts none

    def test_empty_recipient_name_and_unicode(self):
        e = OutboundEmail("", "n@example.com", "r@example.org", "", "Sübject", "<p>héllo 日本</p>")
        obj = build_email_object(e, "", "n@example.com")
        self.assertEqual(obj["to"], [{"email": "r@example.org"}])
        self.assertEqual(obj["from"], {"email": "n@example.com"})
        self.assertIn("日本", base64.b64decode(obj["html"]).decode())

    def test_html_to_text(self):
        t = html_to_text("<style>p{}</style><h1>Title</h1><p>One<br>Two <a href='https://a.b/c'>link</a></p>"
                         "<a href='#'>skip</a><script>x()</script>")
        self.assertIn("Title", t)
        self.assertIn("link (https://a.b/c)", t)
        self.assertNotIn("x()", t)
        self.assertNotIn("p{}", t)

    @override_settings(SENDPULSE_SENDER_EMAIL="default@example.com", SENDPULSE_SENDER_NAME="Default")
    def test_settings_sender_is_the_fallback(self):
        e = OutboundEmail("", "", "r@example.org", "", "S", "<p>x</p>")
        SendPulseProvider().send(e)
        self.assertEqual(self.fake.accepted[0]["from"], {"email": "default@example.com", "name": "Default"})

    def test_empty_subject_is_permanent_and_not_sent(self):
        e = OutboundEmail("S", "n@example.com", "r@example.org", "", "  ", "<p>x</p>")
        with self.assertRaises(ProviderPermanentError):
            SendPulseProvider().send(e)
        self.assertEqual(self.fake.accepted, [])


# =============================================================================== error classification + duplicate safety
class FailureModeTests(SPBase):
    def classify(self, step):
        self.fake.send_script = [step]
        with self.assertRaises(Exception) as ctx:
            SendPulseProvider().send(self.email())
        return ctx.exception

    def test_400_is_permanent(self):
        self.assertIsInstance(self.classify(("status", 400, {"error_code": 10, "message": "Sender email address missing"})),
                              ProviderPermanentError)

    def test_429_and_rate_burst_code_are_temporary(self):
        self.assertIsInstance(self.classify(("status", 429, {"message": "Too many requests"})), ProviderTemporaryError)
        self.assertIsInstance(self.classify(("status", 400, {"error_code": 2020202020})), ProviderTemporaryError)

    def test_503_temporary_but_500_502_504_are_ambiguous(self):
        self.assertIsInstance(self.classify(("status", 503, {})), ProviderTemporaryError)
        for code in (500, 502, 504):
            self.assertIsInstance(self.classify(("status", code, {})), ProviderAmbiguousError, code)

    def test_403_is_config_error(self):
        self.assertIsInstance(self.classify(("status", 403, {"message": "forbidden"})), ProviderConfigError)

    def test_result_false_is_permanent(self):
        self.assertIsInstance(self.classify(("result_false",)), ProviderPermanentError)

    def test_dropped_connection_after_request_is_ambiguous(self):
        self.assertIsInstance(self.classify(("accept_then_drop",)), ProviderAmbiguousError)
        self.assertIsInstance(self.classify(("drop",)), ProviderAmbiguousError)

    def test_read_timeout_on_send_is_ambiguous(self):
        self.fake.send_script = [("hang", 2.5)]
        with override_settings(SENDPULSE_HTTP_TIMEOUT=1):
            with self.assertRaises(ProviderAmbiguousError):
                SendPulseProvider().send(self.email())

    def test_unresponsive_server_during_auth_is_temporary(self):
        import socket
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
        self.addCleanup(srv.close)
        reset_process_cache()
        with override_settings(SENDPULSE_API_BASE_URL=f"http://127.0.0.1:{srv.getsockname()[1]}", SENDPULSE_HTTP_TIMEOUT=1):
            # token fetch itself would hang -> that is a TEMPORARY failure (nothing was sent)
            with self.assertRaises(ProviderTemporaryError):
                SendPulseProvider().send(self.email())

    def test_connection_refused_is_temporary(self):
        self.fake.stop()
        reset_process_cache()
        with self.assertRaises(ProviderTemporaryError):
            SendPulseProvider().send(self.email())


# =============================================================================== dispatch (idempotency, retries)
class DispatchTests(SPBase):
    def setUp(self):
        super().setUp()
        self.camp = self.sp_campaign(n=1)
        self.camp.provider = "sendpulse"
        self.camp.save()
        self.rcpt = CampaignRecipient.objects.create(campaign=self.camp, contact=self.camp.eligible_contacts_queryset().first())

    def msg(self):
        return OutboundMessage.objects.get(recipient=self.rcpt)

    def test_success_records_provider_message_id(self):
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.ACCEPTED)
        m = self.msg()
        self.assertEqual((m.provider, m.state, m.provider_message_id), ("sendpulse", "accepted", "msg-0001"))

    def test_accepted_is_never_resent(self):
        dispatch.send_recipient(self.camp, self.rcpt)
        for _ in range(3):
            self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.ACCEPTED)
        self.assertEqual(len(self.fake.accepted), 1)

    def test_429_defers_with_backoff_then_succeeds_exactly_once(self):
        self.fake.send_script = [("status", 429, {"message": "Too many requests"})]
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.DEFERRED)
        m = self.msg()
        self.assertEqual(m.state, "deferred")
        self.assertGreater(m.next_attempt_at, timezone.now())
        self.assertEqual(len(self.fake.accepted), 0)
        # still inside the backoff window: not retried
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.DEFERRED)
        self.assertEqual(len(self.fake.accepted), 0)
        OutboundMessage.objects.filter(pk=m.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.ACCEPTED)
        self.assertEqual(len(self.fake.accepted), 1)

    def test_attempts_exhausted_becomes_failed(self):
        self.fake.send_script = [("status", 503, {})] * 3
        for _ in range(3):
            OutboundMessage.objects.filter(recipient=self.rcpt).update(next_attempt_at=None)
            out = dispatch.send_recipient(self.camp, self.rcpt)
        self.assertEqual(out, Outcome.FAILED)
        self.assertEqual(self.msg().state, "failed")

    def test_server_error_after_processing_is_needs_review_and_never_retried(self):
        self.fake.send_script = [("accept_then_status", 500)]
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.REVIEW)
        for _ in range(3):
            self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.REVIEW)
        self.assertEqual(len(self.fake.accepted), 1, "the single message the server processed must not be re-sent")
        self.assertEqual(self.msg().state, "needs_review")

    def test_permanent_error_fails_without_retry(self):
        self.fake.send_script = [("status", 400, {"message": "bad"})]
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.FAILED)
        self.assertEqual(self.msg().attempts, 1)

    @override_settings(SENDPULSE_CLIENT_SECRET="wrong")
    def test_config_error_releases_claim_and_sends_nothing(self):
        self.assertEqual(dispatch.send_recipient(self.camp, self.rcpt), Outcome.CONFIG_ERROR)
        m = self.msg()
        self.assertEqual((m.state, m.attempts), ("queued", 0))


# =============================================================================== full campaign flow
class CampaignFlowTests(SPBase):
    def test_campaign_sends_via_sendpulse_and_freezes_provider(self):
        self.allow_choice()
        camp = self.sp_campaign(n=3)
        with patch.object(BrevoClient, "send_transactional_email") as brevo:
            camp = send_campaign_now(camp)
        brevo.assert_not_called()
        self.assertEqual((camp.status, camp.provider), ("sent", "sendpulse"))
        self.assertEqual(len(self.fake.accepted), 3)
        self.assertEqual(set(camp.recipients.values_list("status", flat=True)), {"sent"})
        self.assertEqual(set(OutboundMessage.objects.filter(campaign=camp).values_list("provider", flat=True)), {"sendpulse"})
        # unsubscribe link is rendered per recipient inside the body
        bodies = [base64.b64decode(e["html"]).decode() for e in self.fake.accepted]
        self.assertTrue(all("/api/unsubscribe/" in b for b in bodies))
        self.assertEqual(len({b for b in bodies}), 3)

    def test_provider_stays_frozen_when_platform_default_changes(self):
        self.allow_choice()
        camp = self.sp_campaign(n=2)
        camp = send_campaign_now(camp)
        p = PlatformSettings.load(); p.active_provider = "brevo"; p.save()
        camp.refresh_from_db()
        from .registry import resolve_provider_name
        self.assertEqual(resolve_provider_name(camp), "sendpulse")

    def test_brevo_campaign_is_unaffected_and_never_touches_sendpulse(self):
        other = self.make_user("brevo_user")
        camp = self.make_campaign(other, n=2, name="B")
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<b@x>"}) as brevo:
            camp = send_campaign_now(camp)
        self.assertEqual((camp.status, camp.provider), ("sent", "brevo"))
        self.assertEqual(brevo.call_count, 2)
        self.assertEqual(self.fake.requests, [])

    def test_both_providers_run_side_by_side(self):
        self.allow_choice()
        sp = self.sp_campaign(n=2, name="SP")
        bv = self.make_campaign(self.owner, n=2, name="BV", prefix="bv")
        bv.requested_provider = "brevo"; bv.save()
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<b@x>"}) as brevo:
            sp = send_campaign_now(sp)
            bv = send_campaign_now(bv)
        self.assertEqual((sp.provider, bv.provider), ("sendpulse", "brevo"))
        self.assertEqual((len(self.fake.accepted), brevo.call_count), (2, 2))

    def test_transient_failure_does_not_silently_switch_provider(self):
        self.allow_choice()
        camp = self.sp_campaign(n=1)
        self.fake.send_script = [("status", 503, {})]
        with patch.object(BrevoClient, "send_transactional_email") as brevo:
            camp = send_campaign_now(camp)
        brevo.assert_not_called()
        self.assertEqual(camp.provider, "sendpulse")
        self.assertEqual(camp.status, "processing")        # waits for its retry; never moves to Brevo

    def test_suppressed_contact_is_not_sent(self):
        self.allow_choice()
        camp = self.sp_campaign(n=2)
        Suppression.objects.create(email="owner0@example.org", reason="hard_bounce")
        send_campaign_now(camp)
        self.assertEqual({e["to"][0]["email"] for e in self.fake.accepted}, {"owner1@example.org"})

    def test_provider_not_ready_blocks_start_with_clear_error(self):
        self.allow_choice()
        camp = self.sp_campaign(n=1)
        with override_settings(SENDPULSE_CLIENT_ID="", SENDPULSE_CLIENT_SECRET=""):
            with self.assertRaises(ValidationAppError):
                send_campaign_now(camp)
        camp.refresh_from_db()
        self.assertEqual((camp.status, camp.provider), ("draft", ""))

    def test_test_email_routes_through_sendpulse(self):
        self.allow_choice()
        camp = self.sp_campaign(n=1)
        from .testsend import send_test_email
        send_test_email(camp, "me@example.org")
        self.assertEqual(self.fake.accepted[0]["to"][0]["email"], "me@example.org")
        self.assertTrue(self.fake.accepted[0]["subject"].startswith("[TEST]"))

    def test_standalone_user_sees_all_providers_only_when_choice_enabled(self):
        self.assertEqual(available_providers(self.owner)["options"], ["brevo"])         # default: unchanged
        self.allow_choice()
        opts = available_providers(self.owner)["options"]
        self.assertIn("sendpulse", opts)
        self.assertIn("brevo", opts)

    def test_company_users_get_sendpulse_unless_the_company_is_explicitly_restricted(self):
        from tenancy.models import Company
        co = Company.objects.create(name="Acme")
        self.owner.company = co
        self.owner.save()
        self.assertEqual(available_providers(self.owner)["options"], ["brevo"])          # choice off: unchanged
        self.allow_choice()
        self.assertIn("sendpulse", available_providers(self.owner)["options"])          # no list -> all offered
        co.allowed_providers = ["brevo"]
        co.save()
        self.assertEqual(available_providers(self.owner)["options"], ["brevo"])         # explicit list restricts
        co.allowed_providers = ["brevo", "sendpulse"]
        co.preferred_provider = "sendpulse"
        co.save()
        info = available_providers(self.owner)
        self.assertEqual((info["options"], info["default"]), (["brevo", "sendpulse"], "sendpulse"))

    def test_company_settings_api_exposes_and_enforces_effective_providers(self):
        from tenancy.models import Company
        co = Company.objects.create(name="Acme2")
        admin = self.make_user("coadmin", role="company_admin")
        admin.company = co
        admin.save()
        c = APIClient(); c.force_authenticate(admin)
        self.assertEqual(c.get("/api/company/settings/").json()["effective_providers"], [])
        self.assertEqual(c.patch("/api/company/settings/", {"preferred_provider": "sendpulse"}, format="json").status_code, 403)
        self.allow_choice()
        self.assertIn("sendpulse", c.get("/api/company/settings/").json()["effective_providers"])
        r = c.patch("/api/company/settings/", {"preferred_provider": "sendpulse"}, format="json")
        self.assertEqual((r.status_code, r.json()["preferred_provider"]), (200, "sendpulse"))

    def test_migration_approves_sendpulse_only_for_fully_approved_companies(self):
        import importlib
        from django.apps import apps
        from tenancy.models import Company
        mig = importlib.import_module("tenancy.migrations.0002_approve_sendpulse_for_fully_approved_companies")
        both = Company.objects.create(name="Both", allowed_providers=["brevo", "smtp"])
        brevo_only = Company.objects.create(name="BrevoOnly", allowed_providers=["brevo"])
        empty = Company.objects.create(name="Empty", allowed_providers=[])
        done = Company.objects.create(name="Done", allowed_providers=["brevo", "smtp", "sendpulse"])
        mig.approve_sendpulse(apps, None)
        mig.approve_sendpulse(apps, None)                                   # idempotent
        for c in (both, brevo_only, empty, done):
            c.refresh_from_db()
        self.assertEqual(both.allowed_providers, ["brevo", "smtp", "sendpulse"])
        self.assertEqual(brevo_only.allowed_providers, ["brevo"])           # deliberate restriction kept
        self.assertEqual(empty.allowed_providers, [])
        self.assertEqual(done.allowed_providers, ["brevo", "smtp", "sendpulse"])

    def test_picker_explains_why_a_provider_is_unavailable(self):
        c = APIClient(); c.force_authenticate(self.owner)
        sp = lambda: next(o for o in c.get("/api/campaigns/providers/").json()["options"] if o["name"] == "sendpulse")
        self.assertIn("switched off", sp()["reason"])
        self.allow_choice()
        from tenancy.models import Company
        co = Company.objects.create(name="Restricted", allowed_providers=["brevo"])
        self.owner.company = co
        self.owner.save()
        self.assertIn("company has not approved", sp()["reason"])

    def test_provider_usage_is_reported_for_platform_company_and_user(self):
        from tenancy.models import Company
        co = Company.objects.create(name="UsageCo")
        self.owner.company = co
        self.owner.save()
        self.allow_choice()
        sp = self.sp_campaign(n=2)
        send_campaign_now(sp)
        admin = self.make_user("root2", role="super_admin")
        cl = APIClient(); cl.force_authenticate(admin)
        self.assertEqual(cl.get("/api/platform/overview/").json()["by_provider"]["sendpulse"]["daily_used"], 2)
        detail = cl.get(f"/api/platform/companies/{co.id}/").json()
        self.assertEqual(detail["by_provider"]["sendpulse"]["daily_used"], 2)
        self.assertEqual(detail["by_provider"]["brevo"]["daily_used"], 0)
        self.assertIn("sendpulse", detail["effective_providers"])
        owner_c = APIClient(); owner_c.force_authenticate(self.owner)
        snap = owner_c.get("/api/auth/me/").json()["quota"]
        self.assertEqual(snap["by_provider"]["sendpulse"]["daily_used"], 2)
        co_admin = self.make_user("coadm2", role="company_admin")
        co_admin.company = co
        co_admin.save()
        ca = APIClient(); ca.force_authenticate(co_admin)
        q = ca.get("/api/company/quotas/").json()
        self.assertEqual(q["by_provider"]["sendpulse"]["daily_used"], 2)
        self.assertIn("sendpulse", q["effective_providers"])
        # another company's usage never leaks in
        other = Company.objects.create(name="Other")
        self.assertEqual(cl.get(f"/api/platform/companies/{other.id}/").json()["by_provider"]["sendpulse"]["daily_used"], 0)

    def test_platform_can_create_a_company_with_sendpulse_assigned(self):
        admin = self.make_user("root3", role="super_admin")
        cl = APIClient(); cl.force_authenticate(admin)
        r = cl.post("/api/platform/companies/", {"name": "NewCo", "allowed_providers": ["brevo", "sendpulse"],
                                                  "preferred_provider": "sendpulse"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["allowed_providers"], ["brevo", "sendpulse"])

    def test_requested_provider_validated_for_user(self):
        c = APIClient(); c.force_authenticate(self.owner)
        r = c.get("/api/campaigns/providers/")
        sp = next(o for o in r.json()["options"] if o["name"] == "sendpulse")
        self.assertEqual((sp["label"], sp["allowed"], sp["ready"], sp["usable"]), ("SendPulse", False, True, False))
        self.allow_choice()
        sp = next(o for o in c.get("/api/campaigns/providers/").json()["options"] if o["name"] == "sendpulse")
        self.assertTrue(sp["usable"])


# =============================================================================== quota + rate
class QuotaAndRateTests(SPBase):
    def setUp(self):
        super().setUp()
        self.allow_choice()

    @override_settings(SENDPULSE_DAILY_LIMIT=2)
    def test_sendpulse_allowance_blocks_campaign_without_affecting_brevo(self):
        camp = self.sp_campaign(n=3)
        with self.assertRaises(ValidationAppError) as ctx:
            send_campaign_now(camp)
        self.assertIn("sendpulse", str(ctx.exception).lower())
        bv = self.make_campaign(self.owner, n=3, name="BV", prefix="bv")
        bv.requested_provider = "brevo"; bv.save()
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<b>"}):
            self.assertEqual(send_campaign_now(bv).status, "sent")

    def test_usage_is_tracked_per_provider_and_credits_not_double_counted(self):
        sp = self.sp_campaign(n=2)
        send_campaign_now(sp)
        bv = self.make_campaign(self.owner, n=3, name="BV", prefix="bv")
        bv.requested_provider = "brevo"; bv.save()
        with patch.object(BrevoClient, "send_transactional_email", return_value={"messageId": "<b>"}):
            send_campaign_now(bv)
        usage = quota.usage_by_provider()
        self.assertEqual((usage["sendpulse"]["daily_used"], usage["brevo"]["daily_used"]), (2, 3))
        # a repeated claim/reserve never charges twice
        quota.reserve_campaign_quota(sp)
        self.assertEqual(quota.usage_by_provider()["sendpulse"]["daily_used"], 2)

    @override_settings(SENDPULSE_RATE_LIMIT=1)
    def test_sendpulse_rate_budget_is_separate_from_brevo(self):
        sp = self.sp_campaign(n=1); sp.provider = "sendpulse"; sp.save()
        bv = self.make_campaign(self.owner, n=1, name="BV", prefix="bv"); bv.provider = "brevo"; bv.save()
        r = CampaignRecipient.objects.create(campaign=sp, contact=sp.eligible_contacts_queryset().first())
        self.assertTrue(ratelimit.may_submit(sp))
        dispatch.send_recipient(sp, r)
        self.assertFalse(ratelimit.may_submit(sp))
        self.assertTrue(ratelimit.may_submit(bv))


# =============================================================================== webhooks
def sign(body: bytes, secret=WEBHOOK_SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookTests(SPBase):
    URL = "/api/providers/sendpulse/webhook/"

    def setUp(self):
        super().setUp()
        self.allow_choice()
        self.camp = self.sp_campaign(n=2)
        send_campaign_now(self.camp)
        self.msg = OutboundMessage.objects.filter(campaign=self.camp).order_by("id").first()
        self.email_addr = self.msg.recipient.contact.email

    def post(self, payload, secret=WEBHOOK_SECRET, sig=None):
        body = json.dumps(payload).encode()
        headers = {"HTTP_X_SIGNATURE": sig if sig is not None else sign(body, secret)} if secret is not None else {}
        return self.client.post(self.URL, body, content_type="application/json", **headers)

    def legacy(self, event, **kw):
        return {"event": event, "message_id": self.msg.provider_message_id, "recipient": self.email_addr,
                "timestamp": 1700000000, "subject": "x", **kw}

    # ---- authenticity
    def test_signature_helper(self):
        self.assertTrue(verify_signature(b"{}", sign(b"{}"), WEBHOOK_SECRET))
        self.assertTrue(verify_signature(b"{}", sign(b"{}")[7:], WEBHOOK_SECRET))       # bare hex accepted
        self.assertFalse(verify_signature(b"{}", sign(b"{}"), "other"))
        self.assertFalse(verify_signature(b"{}", "", WEBHOOK_SECRET))
        self.assertFalse(verify_signature(b"{}", sign(b"{}"), ""))

    def test_bad_missing_and_tampered_signature_rejected(self):
        self.assertEqual(self.post(self.legacy("delivered"), sig="sha256=deadbeef").status_code, 401)
        self.assertEqual(self.post(self.legacy("delivered"), secret=None).status_code, 401)
        body = json.dumps(self.legacy("delivered")).encode()
        r = self.client.post(self.URL, body + b" ", content_type="application/json", HTTP_X_SIGNATURE=sign(body))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(CampaignEvent.objects.count(), 0)

    def test_shared_secret_header_works_like_brevo_and_wrong_one_is_rejected(self):
        body = json.dumps(self.legacy("delivered")).encode()
        ok = self.client.post(self.URL, body, content_type="application/json", HTTP_X_WEBHOOK_SECRET=WEBHOOK_SECRET)
        self.assertEqual((ok.status_code, ok.json()["results"]), (200, ["processed:delivered"]))
        bad = self.client.post(self.URL, body, content_type="application/json", HTTP_X_WEBHOOK_SECRET="nope")
        self.assertEqual(bad.status_code, 401)
        query = self.client.post(self.URL + f"?secret={WEBHOOK_SECRET}", body, content_type="application/json")
        self.assertEqual(query.status_code, 401)                      # not accepted in the URL (it would be logged)

    @override_settings(SENDPULSE_WEBHOOK_SECRET="")
    def test_no_secret_configured_fails_closed(self):
        self.assertEqual(self.post(self.legacy("delivered"), secret="anything").status_code, 503)
        body = b"{}"
        self.assertEqual(self.client.post(self.URL, body, content_type="application/json", HTTP_X_WEBHOOK_SECRET="").status_code, 503)

    def test_invalid_json_with_valid_signature_is_400(self):
        r = self.client.post(self.URL, b"not json", content_type="application/json", HTTP_X_SIGNATURE=sign(b"not json"))
        self.assertEqual(r.status_code, 400)

    # ---- processing
    def test_delivered_updates_recipient_event_and_message_state(self):
        r = self.post(self.legacy("delivered"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"], ["processed:delivered"])
        self.msg.recipient.refresh_from_db(); self.msg.refresh_from_db()
        self.assertEqual((self.msg.recipient.status, self.msg.state), ("delivered", "delivered"))
        ev = CampaignEvent.objects.get()
        self.assertEqual((ev.event_type, ev.campaign_id), ("delivered", self.camp.id))
        self.assertEqual(ev.metadata["provider"], "sendpulse")

    def test_duplicate_event_processed_once(self):
        self.post(self.legacy("delivered"))
        r = self.post(self.legacy("delivered"))
        self.assertEqual(r.json()["results"], ["duplicate-ignored"])
        self.assertEqual(CampaignEvent.objects.count(), 1)
        self.assertEqual(ProviderEventLog.objects.count(), 1)

    def test_status_does_not_regress(self):
        self.post(self.legacy("opened"))
        self.post(self.legacy("delivered"))
        self.msg.recipient.refresh_from_db()
        self.assertEqual(self.msg.recipient.status, "opened")

    def test_hard_bounce_spam_and_unsubscribe_suppress_future_sending(self):
        for ev, reason in (("hard_bounce", "hard_bounce"), ("spam_by_user", "spam_complaint"), ("unsubscribed", "unsubscribed")):
            Suppression.objects.all().delete()
            ProviderEventLog.objects.all().delete(); CampaignEvent.objects.all().delete()
            self.post(self.legacy(ev))
            self.assertEqual(Suppression.objects.get(email=self.email_addr).reason, reason, ev)
            self.assertNotIn(self.email_addr, [c.email for c in self.camp.eligible_contacts_queryset()])

    def test_not_delivered_only_hard_bounces_for_bad_mailbox(self):
        self.post(self.legacy("not_delivered", smtp_server_response_code="550", smtp_server_response_subcode="5.7.1"))
        self.assertFalse(Suppression.objects.filter(email=self.email_addr).exists())      # policy refusal: soft
        ProviderEventLog.objects.all().delete()
        self.post(self.legacy("not_delivered", smtp_server_response_code="550", smtp_server_response_subcode="5.1.1"))
        self.assertTrue(Suppression.objects.filter(email=self.email_addr, reason="hard_bounce").exists())

    def test_click_records_url(self):
        self.post(self.legacy("click", link="https://x.test/p"))
        self.assertEqual(CampaignEvent.objects.get().metadata["clicked_url"], "https://x.test/p")

    def test_new_format_payload_and_event_type_prefix(self):
        payload = {"user_id": 1, "scope": "smtp", "event_type": "smtp.delivered", "occurred_at": "2026-11-20T10:00:00Z",
                   "data": {"message_id": self.msg.provider_message_id, "recipient": self.email_addr}}
        self.assertEqual(self.post(payload).json()["results"], ["processed:delivered"])

    def test_array_payload(self):
        r = self.post([self.legacy("delivered"), self.legacy("opened")])
        self.assertEqual(r.json()["results"], ["processed:delivered", "processed:opened"])

    def test_unknown_and_test_events_ignored(self):
        self.assertEqual(self.post({"event_type": "test"}).json()["results"], ["ignored-unhandled-event"])
        self.assertEqual(self.post(self.legacy("resubscribed")).json()["results"], ["ignored-unhandled-event"])

    # ---- attribution
    def test_unmatched_id_falls_back_to_the_single_recent_message(self):
        p = self.legacy("delivered"); p["message_id"] = "1149317311"     # numeric id as in the legacy docs
        self.assertEqual(self.post(p).json()["results"], ["processed:delivered"])
        self.msg.recipient.refresh_from_db()
        self.assertEqual(self.msg.recipient.status, "delivered")

    def test_ambiguous_attribution_guesses_nothing_but_still_suppresses(self):
        other = self.make_campaign(self.owner, n=0, name="Two")
        contact = self.msg.recipient.contact
        other.requested_provider = "sendpulse"; other.save(); other.contact_lists.add(*contact.lists.all())
        send_campaign_now(other)                                          # same address, second recent message
        p = self.legacy("hard_bounce"); p["message_id"] = "unknown-id"
        out = self.post(p).json()["results"][0]
        self.assertTrue(out.startswith("unattributed-ambiguous"))
        self.assertIn("suppressed", out)
        self.assertEqual(CampaignEvent.objects.count(), 0)
        self.assertTrue(Suppression.objects.filter(email=self.email_addr).exists())

    def test_unknown_recipient_with_unsubscribe_still_suppresses(self):
        out = self.post({"event": "unsubscribed", "recipient": "stranger@example.net", "message_id": "zzz"}).json()["results"][0]
        self.assertTrue(out.startswith("unattributed-none"))
        self.assertTrue(Suppression.objects.filter(email="stranger@example.net").exists())

    def test_failure_rolls_back_so_a_retry_is_reprocessed(self):
        with patch("brevo.webhooks.process_webhook_event", side_effect=RuntimeError("boom")):
            r = self.post(self.legacy("delivered"))
        self.assertEqual(r.status_code, 500)
        self.assertEqual(ProviderEventLog.objects.count(), 0)            # not left behind as a false "duplicate"
        self.assertEqual(self.post(self.legacy("delivered")).json()["results"], ["processed:delivered"])

    def test_brevo_webhook_still_works_independently(self):
        with override_settings(BREVO_WEBHOOK_SECRET="s"):
            r = self.client.post("/api/brevo/webhook/", {"event": "delivered", "email": self.email_addr,
                                 "message-id": "<x@y>", "tags": [f"campaign-{self.camp.id}"]},
                                 content_type="application/json", HTTP_X_WEBHOOK_SECRET="s")
        self.assertEqual(r.status_code, 200)


class StatusPollTests(SPBase):
    def test_poll_feeds_the_same_pipeline_and_is_idempotent(self):
        from .sendpulse_webhooks import sync_recent
        self.allow_choice()
        camp = self.sp_campaign(n=1)
        send_campaign_now(camp)
        m = OutboundMessage.objects.get(campaign=camp)
        self.fake.email_info[m.provider_message_id] = {"smtp_answer_code": "250", "tracking": {"open": 2, "click": 0}}
        first = sync_recent()
        again = sync_recent()
        self.assertEqual(first["events"], 2)
        self.assertEqual(again["events"], 0)
        m.recipient.refresh_from_db()
        self.assertEqual(m.recipient.status, "opened")


# =============================================================================== settings API (credentials)
class SettingsApiTests(SPBase):
    URL = "/api/providers/sendpulse/settings/"

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("root", role="super_admin")
        self.c = APIClient(); self.c.force_authenticate(self.admin)
        # start from "nothing configured" so the UI path is what is under test
        self.ctx = override_settings(SENDPULSE_CLIENT_ID="", SENDPULSE_CLIENT_SECRET="", SENDPULSE_WEBHOOK_SECRET="")
        self.ctx.enable(); self.addCleanup(self.ctx.disable)

    def test_only_platform_admins(self):
        u = APIClient(); u.force_authenticate(self.owner)
        for method, url in (("get", self.URL), ("put", self.URL), ("post", "/api/providers/sendpulse/test/"),
                            ("post", "/api/providers/sendpulse/sync/")):
            self.assertEqual(getattr(u, method)(url, {}, format="json").status_code, 403, url)
        self.assertEqual(APIClient().get(self.URL).status_code, 401)

    def test_saving_without_encryption_key_is_refused(self):
        r = self.c.put(self.URL, {"client_id": ID, "client_secret": SECRET}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ProviderCredential.objects.filter(encrypted_secrets__gt="").exists())

    def test_save_encrypts_never_echoes_and_drives_the_provider(self):
        with override_settings(PROVIDER_CREDENTIALS_KEY=Fernet.generate_key().decode(), SENDPULSE_API_BASE_URL=self.fake.url):
            r = self.c.put(self.URL, {"client_id": ID, "client_secret": SECRET, "webhook_secret": WEBHOOK_SECRET,
                                      "sender_name": "QRM", "sender_email": "news@example.com"}, format="json")
            self.assertEqual(r.status_code, 200)
            blob = json.dumps(r.json())
            for secret in (SECRET, WEBHOOK_SECRET, ID):
                self.assertNotIn(secret, blob)
            self.assertTrue(r.json()["client_secret_set"] and r.json()["webhook_secret_set"])
            self.assertEqual(r.json()["source"], "database")
            row = ProviderCredential.objects.get(provider="sendpulse")
            dump = " ".join(str(v) for v in row.__dict__.values())
            for secret in (SECRET, WEBHOOK_SECRET, ID):
                self.assertNotIn(secret, dump)
            # the stored credentials really are what the provider uses
            self.assertEqual(SendPulseProvider().send(self.email()).message_id, "msg-0001")
            # a later partial update keeps the secrets
            r2 = self.c.put(self.URL, {"sender_name": "New"}, format="json")
            self.assertEqual(r2.json()["sender_name"], "New")
            self.assertTrue(r2.json()["client_secret_set"])
            self.assertEqual(SendPulseProvider().send(self.email()).message_id, "msg-0002")
            # audit entry never contains values
            from tenancy.models import AuditLog
            self.assertNotIn(SECRET, json.dumps(list(AuditLog.objects.values_list("detail", flat=True))))

    def test_rotating_the_secret_discards_the_old_token(self):
        with override_settings(PROVIDER_CREDENTIALS_KEY=Fernet.generate_key().decode()):
            self.c.put(self.URL, {"client_id": ID, "client_secret": SECRET}, format="json")
            SendPulseProvider().send(self.email())
            self.assertTrue(ProviderCredential.objects.get().encrypted_token)
            self.c.put(self.URL, {"client_secret": "new-secret"}, format="json")
            row = ProviderCredential.objects.get()
            self.assertEqual((row.encrypted_token, row.token_fingerprint), ("", ""))
            with self.assertRaises(ProviderConfigError):          # the fake server only knows the old secret
                SendPulseProvider().send(self.email())

    def test_undecryptable_stored_credentials_never_fall_back_to_the_environment(self):
        with override_settings(PROVIDER_CREDENTIALS_KEY=Fernet.generate_key().decode()):
            self.c.put(self.URL, {"client_id": ID, "client_secret": SECRET}, format="json")
        with override_settings(PROVIDER_CREDENTIALS_KEY=Fernet.generate_key().decode(),
                               SENDPULSE_CLIENT_ID=ID, SENDPULSE_CLIENT_SECRET=SECRET):
            with self.assertRaises(ProviderConfigError):
                SendPulseProvider().validate_config()

    def test_validation(self):
        with override_settings(PROVIDER_CREDENTIALS_KEY=Fernet.generate_key().decode()):
            self.assertEqual(self.c.put(self.URL, {"sender_email": "nope"}, format="json").status_code, 400)
            self.assertEqual(self.c.put(self.URL, {"client_id": ID}, format="json").status_code, 400)

    def test_test_connection_reports_status_and_sends_no_email(self):
        with override_settings(SENDPULSE_CLIENT_ID=ID, SENDPULSE_CLIENT_SECRET=SECRET, SENDPULSE_SENDER_EMAIL="news@example.com"):
            r = self.c.post("/api/providers/sendpulse/test/", {}, format="json")
            self.assertTrue(r.json()["ok"], r.json())
            self.assertEqual(r.json()["account"]["smtp_plan"], "SMTP Free")
            self.assertEqual(self.fake.accepted, [])
            self.assertEqual(self.c.get(self.URL).json()["status"]["state"], "connected")
            self.fake.senders = []
            r = self.c.post("/api/providers/sendpulse/test/", {}, format="json")
            self.assertTrue(r.json()["ok"])
            self.assertTrue(r.json()["warnings"])

    def test_test_connection_with_bad_credentials_fails_cleanly(self):
        with override_settings(SENDPULSE_CLIENT_ID=ID, SENDPULSE_CLIENT_SECRET="bad"):
            r = self.c.post("/api/providers/sendpulse/test/", {}, format="json")
            self.assertFalse(r.json()["ok"])
            self.assertNotIn("bad", json.dumps(r.json()).replace("Client authentication failed", ""))
            self.assertEqual(self.c.get(self.URL).json()["status"]["state"], "failed")

    def test_health_endpoint_lists_sendpulse(self):
        with override_settings(SENDPULSE_CLIENT_ID=ID, SENDPULSE_CLIENT_SECRET=SECRET):
            with patch.object(BrevoClient, "get_account", return_value={}):
                r = self.c.get("/api/platform/health/")
        self.assertTrue(r.json()["providers"]["sendpulse"]["ok"])

    def test_quota_overview_includes_per_provider_usage(self):
        r = self.c.get("/api/platform/quotas/")
        self.assertIn("sendpulse", r.json()["by_provider"])

    def test_platform_can_activate_sendpulse_only_when_configured(self):
        with override_settings(SENDPULSE_CLIENT_ID="", SENDPULSE_CLIENT_SECRET=""):
            self.assertEqual(self.c.patch("/api/platform/settings/", {"active_provider": "sendpulse"}, format="json").status_code, 400)
        with override_settings(SENDPULSE_CLIENT_ID=ID, SENDPULSE_CLIENT_SECRET=SECRET):
            self.assertEqual(self.c.patch("/api/platform/settings/", {"active_provider": "sendpulse"}, format="json").status_code, 200)


class ProviderLogApiTests(SPBase):
    def test_owner_sees_own_campaign_log_only(self):
        self.allow_choice()
        camp = self.sp_campaign(n=2)
        self.fake.send_script = [("status", 400, {"message": "bad address"})]
        send_campaign_now(camp)
        c = APIClient(); c.force_authenticate(self.owner)
        r = c.get(f"/api/campaigns/{camp.id}/provider-log/").json()
        self.assertEqual((r["provider"], r["frozen"], r["total"]), ("sendpulse", True, 2))
        self.assertEqual(r["states"], {"failed": 1, "accepted": 1})
        self.assertIn("bad address", r["recent_errors"][0]["error"])
        stranger = APIClient(); stranger.force_authenticate(self.make_user("stranger"))
        self.assertEqual(stranger.get(f"/api/campaigns/{camp.id}/provider-log/").status_code, 404)


# =============================================================================== LIVE (needs real credentials)
LIVE_ID = os.getenv("SENDPULSE_LIVE_CLIENT_ID", "")
LIVE_SECRET = os.getenv("SENDPULSE_LIVE_CLIENT_SECRET", "")


@unittest.skipUnless(LIVE_ID and LIVE_SECRET, "needs SENDPULSE_LIVE_CLIENT_ID / SENDPULSE_LIVE_CLIENT_SECRET (real SendPulse account)")
class LiveSendPulseTests(TestCase):
    """Run against the REAL api.sendpulse.com. Read-only unless SENDPULSE_LIVE_TEST_RECIPIENT is also set."""

    def setUp(self):
        reset_process_cache()
        ctx = override_settings(SENDPULSE_API_BASE_URL="https://api.sendpulse.com", SENDPULSE_CLIENT_ID=LIVE_ID,
                                SENDPULSE_CLIENT_SECRET=LIVE_SECRET, SENDPULSE_MIN_SEND_INTERVAL_MS=120)
        ctx.enable(); self.addCleanup(ctx.disable)

    def test_authentication_and_account(self):
        r = SendPulseProvider().test_connection()
        self.assertTrue(r["ok"], r)

    def test_invalid_secret_is_rejected_by_the_real_service(self):
        with override_settings(SENDPULSE_CLIENT_SECRET="definitely-wrong"):
            self.assertFalse(SendPulseProvider().test_connection()["ok"])

    @unittest.skipUnless(os.getenv("SENDPULSE_LIVE_TEST_RECIPIENT") and os.getenv("SENDPULSE_LIVE_SENDER"),
                         "needs SENDPULSE_LIVE_TEST_RECIPIENT and SENDPULSE_LIVE_SENDER (a sender verified in SendPulse)")
    def test_real_send_returns_a_message_id(self):
        e = OutboundEmail("QRM live test", os.environ["SENDPULSE_LIVE_SENDER"], os.environ["SENDPULSE_LIVE_TEST_RECIPIENT"],
                          "", "SendPulse integration live test", "<p>Live test from the integration suite.</p>")
        res = SendPulseProvider().send(e)
        self.assertTrue(res.message_id)