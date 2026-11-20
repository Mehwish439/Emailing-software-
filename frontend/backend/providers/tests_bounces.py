"""Bounce / complaint pipeline tests (Postfix-style DSN + ARF samples; HMAC-signed webhook)."""
import hashlib
import hmac

from django.test import Client, TestCase, override_settings

from analytics.models import CampaignEvent
from campaigns.models import Campaign, CampaignRecipient
from contacts.models import Contact, Suppression

from .bounces import classify, ingest_report, parse_report
from .models import OutboundMessage
from .smtp_provider import verp_return_path
from .tests import Fixture

DSN = """\
From: MAILER-DAEMON@mx.example.com
To: {rcpt_to}
Subject: Undelivered Mail Returned to Sender
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="BND"

--BND
Content-Type: text/plain

This is the mail system. Your message could not be delivered.
--BND
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.example.com
X-Postfix-Queue-ID: 4F1A2B3C

Final-Recipient: rfc822; {email}
Original-Recipient: rfc822;{email}
Action: {action}
Status: {status}
Diagnostic-Code: smtp; 550 5.1.1 <{email}>: Recipient address rejected: User unknown

--BND
Content-Type: text/rfc822-headers

Message-ID: <abc123@example.com>
X-Campaign-Id: {camp}
X-Recipient-Id: {rcpt}
Subject: Hello

--BND--
"""

ARF = """\
From: complaints@isp.example
To: {rcpt_to}
Subject: Abuse report
MIME-Version: 1.0
Content-Type: multipart/report; report-type=feedback-report; boundary="ARF"

--ARF
Content-Type: text/plain

This is an email abuse report.
--ARF
Content-Type: message/feedback-report

Feedback-Type: abuse
User-Agent: ISP-FBL/1.0
Version: 1
Original-Rcpt-To: {email}

--ARF
Content-Type: text/rfc822-headers

Message-ID: <abc123@example.com>
X-Campaign-Id: {camp}
X-Recipient-Id: {rcpt}

--ARF--
"""


class BounceTests(Fixture, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.camp = self.make_campaign(self.user, n=2)
        self.camp.status, self.camp.provider = Campaign.Status.PROCESSING, "smtp"
        self.camp.save()
        self.contact = Contact.objects.get(email="owner0@example.org")
        self.rcpt = CampaignRecipient.objects.create(campaign=self.camp, contact=self.contact, status="sent")
        OutboundMessage.objects.create(idempotency_key="k", campaign=self.camp, recipient=self.rcpt,
                                       provider="smtp", state="accepted")

    def dsn(self, status="5.1.1", action="failed", verp=True, camp=None, rcpt=None, email=None):
        with override_settings(SMTP_BOUNCE_DOMAIN="bounce.example.com"):
            to = verp_return_path(self.rcpt.id, self.camp.id) if verp else "bounces@example.com"
        return DSN.format(rcpt_to=to, email=email or self.contact.email, action=action, status=status,
                          camp=camp or self.camp.id, rcpt=rcpt or self.rcpt.id).replace("\n", "\r\n").encode()

    @override_settings(SMTP_BOUNCE_DOMAIN="bounce.example.com")
    def test_hard_bounce_updates_everything_and_suppresses(self):
        out = ingest_report(self.dsn())
        self.assertEqual(out, ["processed:hard_bounce"])
        self.rcpt.refresh_from_db()
        self.assertEqual(self.rcpt.status, "bounced")
        self.assertTrue(Suppression.objects.filter(email=self.contact.email, reason="hard_bounce").exists())
        ev = CampaignEvent.objects.get()
        self.assertEqual((ev.event_type, ev.metadata["provider"], ev.metadata["dsn_status"]), ("hard_bounce", "smtp", "5.1.1"))
        self.assertEqual(OutboundMessage.objects.get().state, "bounced")

    @override_settings(SMTP_BOUNCE_DOMAIN="bounce.example.com")
    def test_duplicate_bounce_is_ignored(self):
        ingest_report(self.dsn())
        self.assertEqual(ingest_report(self.dsn()), ["duplicate-ignored"])
        self.assertEqual(CampaignEvent.objects.count(), 1)

    @override_settings(SMTP_BOUNCE_DOMAIN="bounce.example.com")
    def test_soft_bounce_and_delay_never_suppress(self):
        self.assertEqual(ingest_report(self.dsn(status="4.2.2", action="delayed")), ["processed:soft_bounce"])
        self.assertFalse(Suppression.objects.exists())
        other = self.dsn(status="5.2.2")                      # mailbox full: permanent code, soft in practice
        self.assertEqual(parse_report(other)[0]["event"], "soft_bounce")

    def test_attribution_falls_back_to_original_headers_without_verp(self):
        out = ingest_report(self.dsn(verp=False))
        self.assertEqual(out, ["processed:hard_bounce"])

    @override_settings(SMTP_BOUNCE_DOMAIN="bounce.example.com")
    def test_forged_verp_cannot_attribute_to_another_recipient(self):
        raw = self.dsn().replace(f".{self.rcpt.id}.".encode(), b".999.")
        events = parse_report(raw)
        # signature mismatch -> VERP rejected -> falls back to the (genuine) original headers,
        # never to the forged ids
        self.assertEqual(events[0]["recipient_id"], self.rcpt.id)

    def test_unattributable_bounce_is_ignored_not_guessed(self):
        raw = self.dsn(verp=False).replace(b"X-Campaign-Id", b"X-Nope").replace(b"X-Recipient-Id", b"X-Nope2")
        self.assertEqual(ingest_report(raw), ["ignored-unattributable"])
        self.assertFalse(CampaignEvent.objects.exists())
        self.assertFalse(Suppression.objects.exists())

    def test_relayed_and_delivered_notices_are_not_treated_as_delivery(self):
        self.assertIsNone(classify("relayed", "2.0.0"))
        self.assertIsNone(classify("delivered", "2.0.0"))
        self.assertEqual(parse_report(self.dsn(status="2.0.0", action="relayed")), [])

    def test_policy_block_is_classified_blocked(self):
        self.assertEqual(classify("failed", "5.7.1"), "blocked")
        self.assertEqual(classify("failed", "5.1.1"), "hard_bounce")
        self.assertEqual(classify("failed", "4.4.1"), "soft_bounce")

    def test_arf_complaint_marks_spam_and_suppresses(self):
        raw = ARF.format(rcpt_to="fbl@example.com", email=self.contact.email, camp=self.camp.id,
                         rcpt=self.rcpt.id).replace("\n", "\r\n").encode()
        self.assertEqual(ingest_report(raw), ["processed:spam"])
        self.assertTrue(Suppression.objects.filter(email=self.contact.email, reason="spam_complaint").exists())
        self.rcpt.refresh_from_db()
        self.assertEqual(self.rcpt.status, "spam")

    def test_suppressed_recipient_is_excluded_from_next_campaign(self):
        ingest_report(self.dsn(verp=False))
        again = self.make_campaign(self.user, n=0, name="Next")
        again.contact_lists.add(self.camp.contact_lists.first())
        emails = set(again.eligible_contacts_queryset().values_list("email", flat=True))
        self.assertNotIn(self.contact.email, emails)
        self.assertIn("owner1@example.org", emails)


class BounceWebhookTests(Fixture, TestCase):
    URL = "/api/providers/smtp/bounce/"

    def sign(self, body, secret="s3cret"):
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_disabled_without_secret(self):
        with override_settings(SMTP_BOUNCE_WEBHOOK_SECRET=""):
            r = Client().post(self.URL, b"x", content_type="message/rfc822")
        self.assertEqual(r.status_code, 503)

    @override_settings(SMTP_BOUNCE_WEBHOOK_SECRET="s3cret")
    def test_bad_or_missing_signature_rejected(self):
        c = Client()
        self.assertEqual(c.post(self.URL, b"x", content_type="message/rfc822").status_code, 401)
        r = c.post(self.URL, b"x", content_type="message/rfc822", HTTP_X_SIGNATURE=self.sign(b"x", "wrong"))
        self.assertEqual(r.status_code, 401)

    @override_settings(SMTP_BOUNCE_WEBHOOK_SECRET="s3cret")
    def test_signed_request_processed_and_get_not_allowed(self):
        body = b"From: a@b.c\r\nSubject: junk\r\n\r\nnot a dsn"
        r = Client().post(self.URL, body, content_type="message/rfc822", HTTP_X_SIGNATURE=self.sign(body))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"results": []})
        self.assertEqual(Client().get(self.URL).status_code, 405)

    @override_settings(SMTP_BOUNCE_WEBHOOK_SECRET="s3cret")
    def test_oversized_payload_rejected(self):
        body = b"x" * 1_000_001
        r = Client().post(self.URL, body, content_type="message/rfc822", HTTP_X_SIGNATURE=self.sign(body))
        self.assertEqual(r.status_code, 413)
