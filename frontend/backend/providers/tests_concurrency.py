"""
Concurrency proofs. These need a real PostgreSQL (row locks are no-ops on SQLite), so they skip
themselves elsewhere:   DATABASE_URL=postgres://... python manage.py test providers.tests_concurrency
Each worker thread has its own DB connection and starts at the same instant (Barrier).
"""
import threading
import time
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, connections
from django.test import TransactionTestCase, override_settings

from brevo.client import BrevoClient
from campaigns.models import Campaign, CampaignRecipient
from campaigns.services import build_recipient_snapshot, resume_stuck_campaigns, send_campaign_now
from common.exceptions import ValidationAppError
from contacts.models import Contact
from tenancy import quota
from tenancy.models import Company, Plan, QuotaLedger

from . import dispatch
from .base import BaseProvider, SendResult
from .dispatch import Outcome
from .models import OutboundMessage
from .tests import Fixture, Recorder, smtp_server, smtp_settings

postgres_only = skipUnless(connection.vendor == "postgresql", "needs PostgreSQL row locking")


def run_parallel(fns):
    """Run callables simultaneously; return their results (or the exception raised)."""
    barrier, results = threading.Barrier(len(fns)), [None] * len(fns)

    def worker(i, fn):
        try:
            barrier.wait(timeout=10)
            results[i] = fn()
        except Exception as exc:  # noqa: BLE001
            results[i] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    return results


@postgres_only
class QuotaConcurrencyTests(Fixture, TransactionTestCase):
    def test_simultaneous_campaigns_cannot_jointly_exceed_a_user_limit(self):
        user = self.make_user("racer", daily_quota=100, monthly_quota=1000)
        camps = []
        for i in range(8):
            c = self.make_campaign(user, n=30, name=f"C{i}", prefix=f"r{i}x")
            build_recipient_snapshot(c)
            camps.append(c)
        results = run_parallel([lambda c=c: quota.reserve_campaign_quota(c) for c in camps])
        ok = [r for r in results if r == 30]
        rejected = [r for r in results if isinstance(r, ValidationAppError)]
        self.assertEqual((len(ok), len(rejected)), (3, 5), results)      # 3 x 30 = 90 <= 100; a 4th would be 120
        self.assertEqual(QuotaLedger.objects.count(), 90)
        self.assertLessEqual(quota.usage(user=user)[0], 100)

    def test_company_limit_holds_across_different_users_racing(self):
        plan = Plan.objects.create(name="P", daily_quota=100, monthly_quota=10000, max_users=9)
        company = Company.objects.create(name="Racing Co", plan=plan)
        users = [self.make_user(f"u{i}", company=company, daily_quota=100, monthly_quota=10000) for i in range(6)]
        camps = []
        for i, u in enumerate(users):
            c = self.make_campaign(u, n=40, name=f"K{i}", prefix=f"k{i}y")
            build_recipient_snapshot(c)
            camps.append(c)
        results = run_parallel([lambda c=c: quota.reserve_campaign_quota(c) for c in camps])
        self.assertEqual(sum(1 for r in results if r == 40), 2, results)     # 2 x 40 = 80 <= 100
        self.assertEqual(quota.usage(company=company)[0], 80)

    def test_platform_budget_holds_across_companies_racing(self):
        from tenancy.models import PlatformSettings
        PlatformSettings.objects.update_or_create(pk=1, defaults={"daily_budget": 50})
        camps = []
        for i in range(5):
            u = self.make_user(f"p{i}")
            c = self.make_campaign(u, n=20, name=f"P{i}", prefix=f"pp{i}z")
            build_recipient_snapshot(c)
            camps.append(c)
        results = run_parallel([lambda c=c: quota.reserve_campaign_quota(c) for c in camps])
        self.assertEqual(sum(1 for r in results if r == 20), 2, results)     # 2 x 20 = 40 <= 50
        self.assertEqual(quota.usage(platform=True)[0], 40)

    def test_same_campaign_reserved_twice_concurrently_charges_once(self):
        user = self.make_user("dup", daily_quota=100, monthly_quota=1000)
        c = self.make_campaign(user, n=25)
        build_recipient_snapshot(c)
        run_parallel([lambda: quota.reserve_campaign_quota(c) for _ in range(6)])
        self.assertEqual(QuotaLedger.objects.count(), 25)


class SlowProvider(BaseProvider):
    name = "smtp"

    def __init__(self):
        self.calls, self.lock = 0, threading.Lock()

    def validate_config(self):
        pass

    def send(self, email):
        with self.lock:
            self.calls += 1
        time.sleep(0.4)           # widen the race window
        return SendResult(provider="smtp", message_id="<m@x>")


@postgres_only
class DispatchConcurrencyTests(Fixture, TransactionTestCase):
    def test_same_recipient_submitted_by_many_workers_is_sent_exactly_once(self):
        user = self.make_user()
        camp = self.make_campaign(user, n=1)
        camp.provider, camp.status = "smtp", Campaign.Status.PROCESSING
        camp.save()
        rcpt = CampaignRecipient.objects.create(campaign=camp, contact=Contact.objects.get())
        provider = SlowProvider()
        with patch("providers.dispatch.get_provider", return_value=provider):
            results = run_parallel([lambda: dispatch.send_recipient(camp, rcpt) for _ in range(10)])
        self.assertEqual(provider.calls, 1, results)
        self.assertEqual(results.count(Outcome.ACCEPTED), 1)
        self.assertTrue(all(r in (Outcome.ACCEPTED, Outcome.BUSY) for r in results), results)
        self.assertEqual(OutboundMessage.objects.count(), 1)

    def test_parallel_resume_runs_never_duplicate_emails(self):
        ctrl, rec, port = smtp_server()
        self.addCleanup(ctrl.stop)
        from tenancy.models import PlatformSettings
        PlatformSettings.objects.update_or_create(pk=1, defaults={"active_provider": "smtp"})
        user = self.make_user()
        camp = self.make_campaign(user, n=12)
        with smtp_settings(port), override_settings(CAMPAIGN_SEND_BATCH_SIZE=3), \
                patch.object(BrevoClient, "send_transactional_email") as brevo:
            send_campaign_now(camp)                                # first batch of 3
            for _ in range(4):                                     # four rounds of 4 racing cron ticks
                run_parallel([resume_stuck_campaigns for _ in range(4)])
        brevo.assert_not_called()
        recipients = [m.rcpt_tos[0] for m in rec.messages]
        self.assertEqual(len(recipients), 12, recipients)
        self.assertEqual(len(set(recipients)), 12, "a recipient received the same email twice")
        camp.refresh_from_db()
        self.assertEqual(camp.status, Campaign.Status.SENT)
        self.assertEqual(QuotaLedger.objects.filter(state="consumed").count(), 12)
