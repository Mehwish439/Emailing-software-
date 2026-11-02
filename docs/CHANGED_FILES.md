# Changed and new files (Phase 1)

## Modified (existing files)
- `.gitignore` — ignore SMTP package config/keys
- `backend/.env.example` — new provider / SMTP / Celery variables (Brevo variables unchanged)
- `backend/requirements.txt` — `celery`, `redis` (optional at runtime)
- `backend/config/settings.py` — new apps, `EMAIL_PROVIDER`, `SMTP_*`, optional `CELERY_*`, test-only Brevo placeholder key
- `backend/config/urls.py` — `/api/providers/…`, `/api/company/…`, `/api/platform/…`
- `backend/config/__init__.py` — optional Celery app import (app runs without Celery installed)
- `backend/accounts/{models,serializers,urls,views}.py` — role/company/quotas on User (read-only to the user), accept-invite endpoint
- `backend/brevo/services.py` — `send_to_recipient` now uses the shared message builder (Brevo behaviour unchanged)
- `backend/brevo/webhooks.py` — mirrors events onto `OutboundMessage`
- `backend/campaigns/models.py` — `Campaign.provider`, `Status.PAUSED`, `Campaign.segments` restored (fixes pre-existing model/migration drift)
- `backend/campaigns/services.py` — provider frozen + quota reserved at claim; sends via the idempotent dispatcher
- `backend/campaigns/views.py` — "Send test" routed through the active provider
- `backend/scheduling/services.py` — job heartbeat

## New
- `backend/tenancy/` — Company, Plan, PlatformSettings, QuotaLedger, AuditLog, JobHeartbeat; quota service; company-admin and platform-admin APIs; tests
- `backend/providers/` — provider interface, Brevo + SMTP providers, shared builder, idempotent dispatcher, fair rate limiter, bounce/DSN/ARF parser + signed webhook, Celery tasks, test-send routing, tests (incl. real-SMTP-server and PostgreSQL concurrency tests)
- `backend/config/celery.py`, `backend/requirements-dev.txt`
- migrations: `accounts/0002`, `campaigns/0004`, `tenancy/0001`, `providers/0001` (all additive)
- `deployment/self-hosted-smtp/` — complete Postfix + OpenDKIM package (see its README)
- `docs/UPGRADE_NOTES.md`, `docs/CHANGED_FILES.md`

## Not changed
`frontend/` (Phase 2), `render.yaml`, existing Brevo client/webhook endpoints, existing migrations.
