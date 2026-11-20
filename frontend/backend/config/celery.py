"""
Optional Celery app. The platform works WITHOUT it (the existing cron-driven
`manage.py process_scheduled_campaigns` / POST /api/scheduling/process-due/ keeps working);
Celery + Redis simply replace the external cron trigger and add retry/monitoring.
The database remains the source of truth for campaign state and quota -- Redis only carries
"run now" signals, so losing Redis loses no campaign or quota data.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mailflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["providers", "tenancy"])
