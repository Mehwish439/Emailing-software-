"""Read ONE bounce/ARF message from stdin (for Postfix `pipe` delivery when Django runs on the same host)."""
import sys

from django.core.management.base import BaseCommand

from providers.bounces import ingest_report


class Command(BaseCommand):
    help = "Ingest a single bounce/feedback message from stdin."

    def add_arguments(self, parser):
        parser.add_argument("--recipient", default="", help="Envelope recipient (the VERP address).")

    def handle(self, *args, **opts):
        results = ingest_report(sys.stdin.buffer.read(), opts["recipient"])
        self.stdout.write(f"processed: {results}")
