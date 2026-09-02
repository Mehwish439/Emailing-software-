"""
python manage.py process_scheduled_campaigns

Intended to run on a schedule (e.g. every minute) via cron:

    * * * * * cd /path/to/backend && /path/to/venv/bin/python manage.py process_scheduled_campaigns >> /var/log/campaign-cron.log 2>&1

This replaces the previous Celery ETA/Beat-based scheduling. There is no
task queue or worker process in this architecture — cron itself is the
scheduler, and this command is where the actual work happens.

If you don't have real cron access (e.g. a free-tier PaaS web service),
POST /api/scheduling/process-due/ triggers the exact same logic over HTTP —
see scheduling/views.py and the deploy guide (docs/RENDER_DEPLOY.md) for
using a free external scheduler like cron-job.org against that endpoint
instead of this command.

Safety against duplicate/overlapping runs
------------------------------------------
Cron may invoke this command again while a previous invocation is still
running (e.g. a slow Brevo API call makes one run take longer than a
minute), and in a multi-instance deployment more than one host may run cron
at once (or an HTTP-triggered run may overlap a cron run). To make that safe:

  - Each due ScheduledCampaign is claimed one at a time inside its own
    `transaction.atomic()` block using `SELECT ... FOR UPDATE SKIP LOCKED`
    (on backends that support it — Postgres/Supabase does; SQLite does not,
    and falls back to a plain row lock, which is sufficient for local/test
    use with a single process).
  - Claiming means atomically checking status == SCHEDULED and immediately
    flipping it to PROCESSING in the same transaction. A second process
    trying to claim the same row either blocks until the first transaction
    commits (then sees status == PROCESSING and skips it) or, with
    SKIP LOCKED, skips the locked row immediately and moves on to the next
    one — either way, the same schedule is never claimed twice.
  - The actual sending happens *outside* that transaction (via
    campaigns.services.send_campaign_now, which does its own short-lived
    row lock on the Campaign itself) so a slow Brevo API call never holds a
    database lock for its full duration.

See scheduling/services.py's process_due_schedules() for the actual
claim/send/finalize logic — this command is just a thin wrapper around it.
"""
from django.core.management.base import BaseCommand

from scheduling.services import process_due_schedules


class Command(BaseCommand):
    help = "Processes due scheduled campaigns and sends them via Brevo. Run periodically (e.g. every minute) via cron."

    def handle(self, *args, **options):
        results = process_due_schedules()

        if not results:
            self.stdout.write("process_scheduled_campaigns: no due schedules found.")
            return

        for r in results:
            if r["result"] == "sent":
                self.stdout.write(self.style.SUCCESS(f"Schedule {r['schedule_id']} (campaign {r['campaign_id']}) sent."))
            else:
                self.stderr.write(self.style.ERROR(f"Schedule {r['schedule_id']} failed: {r['detail']}"))

        self.stdout.write(
            self.style.SUCCESS(f"process_scheduled_campaigns: processed {len(results)} due schedule(s).")
        )