from django.core.management.base import BaseCommand, CommandError

from providers.base import ProviderConfigError
from providers.sendpulse_webhooks import sync_recent


class Command(BaseCommand):
    help = "Poll SendPulse for delivery/open/click status of recently accepted messages (fallback to webhooks)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--max-age-days", type=int, default=3)

    def handle(self, *args, **opts):
        try:
            stats = sync_recent(limit=opts["limit"], max_age_days=opts["max_age_days"])
        except ProviderConfigError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"checked={stats['checked']} events={stats['events']} errors={stats['errors']}")
