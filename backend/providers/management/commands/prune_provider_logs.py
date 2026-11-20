from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from providers.models import ProviderEventLog


class Command(BaseCommand):
    help = "Delete provider event-log rows older than PROVIDER_LOG_RETENTION_DAYS (or --days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.PROVIDER_LOG_RETENTION_DAYS)

    def handle(self, *args, **opts):
        n, _ = ProviderEventLog.objects.filter(received_at__lt=timezone.now() - timedelta(days=opts["days"])).delete()
        self.stdout.write(f"Deleted {n} provider log row(s).")
