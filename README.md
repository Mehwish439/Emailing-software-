# Email Campaign Management Platform

A full-stack email campaign management application: create contacts, build email
templates, assemble campaigns, send immediately or schedule for later in any
timezone, and track delivery/open/click/bounce analytics — backed by a Django
REST API, Supabase PostgreSQL, a cron-driven Django management command for
scheduled sends, and the Brevo email delivery API.

---

## 1. Project Overview

| Layer | Technology |
|---|---|
| Backend API | Django 5 + Django REST Framework |
| Auth | JWT (SimpleJWT), access + refresh tokens |
| Database | Supabase PostgreSQL (plain Django ORM over a standard Postgres connection) |
| Scheduled/background campaign processing | Cron → `python manage.py process_scheduled_campaigns` |
| Email delivery | Brevo API (transactional send) |
| Frontend | React 18 + Vite + Tailwind CSS |
| HTTP client | Axios (with automatic token refresh) |

Core features: contact & list management with CSV import, email template
editor, 5-step campaign creation wizard, send-now or schedule-for-later with
timezone support, Brevo webhook-driven analytics (delivered/opened/clicked/
bounced/spam/unsubscribed), suppression list enforcement, and a full SaaS-style
dashboard UI.

**This is a deliberately simple MVP architecture: there is no task queue,
no worker process, and no Redis.** Campaign sending is a plain synchronous
Django function call; "send now" calls it directly from an API request, and
scheduled sends are triggered by an ordinary cron job invoking a Django
management command on a fixed interval. See section 20 for why, and what
that trades off.

---

## 2. Architecture

```
React/Vite  ────HTTP/JSON────▶  Django REST API  ────▶  Supabase PostgreSQL
                                       │                        ▲
                          views.py ──▶ services.py              │
                                       │                         │
                          (Brevo) services.py ──▶ brevo/client.py ──▶ Brevo API
                                                                  │
                          Cron (every minute) ──▶ process_scheduled_campaigns
                                                   management command ──▶ same
                                                   campaigns.services functions
                                                   as "Send Now" ──▶ Brevo API
                                                                  │
                          Brevo Webhook ──▶ brevo/webhooks.py ──▶ CampaignEvent ──▶ Analytics
```

Each Django app follows the same layering: `views.py` never talks to Brevo or
does complex queries directly — it calls `services.py`, which owns business
logic and (for anything Brevo-related) calls `brevo/services.py`, which in
turn calls the thin HTTP wrapper in `brevo/client.py`.

**Send Now** and **scheduled sends** are two entry points into the *same*
function, `campaigns.services.send_campaign_now()` — there is exactly one
place campaign-sending logic lives:

```
Send Now API  ──┐
                 ├──▶  campaigns.services.send_campaign_now()  ──▶  brevo/services.py  ──▶  Brevo API
Cron → process_scheduled_campaigns  ──┘
```

---

## 3. Requirements

- Python 3.12+
- Node.js 18+ and npm
- A Supabase account/project (its built-in PostgreSQL database)
- A Brevo account and API key (free tier is fine for testing)
- Cron-capable hosting for production (any Linux host, or your platform's
  scheduled-job feature — see section 12)

There is no Redis or Celery to install.

---

## 4. Supabase Setup

1. Create a project at [supabase.com](https://supabase.com).
2. Go to **Settings → Database → Connection string**. Supabase shows two
   relevant options:
   - **Connection pooling** (pgbouncer) — recommended for this app. It's
     built for many short-lived connections, which fits a web app plus a
     periodic cron process well.
   - **Direct connection** — also works; simpler, but less suited to bursty
     connection patterns at scale.
3. Copy whichever connection string you choose into `backend/.env` as
   `DATABASE_URL` (see section 8).

Django connects to it exactly like any other PostgreSQL database via
`psycopg2` and the standard ORM — no Supabase client library or REST API is
used anywhere in this project; Supabase is used purely as the Postgres host.

---

## 5. Backend Setup

```bash
cd backend

python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt

copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux

# edit .env with your Supabase DATABASE_URL, BREVO_API_KEY, etc.

python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

The API is now running at `http://localhost:8000/`. Django admin is at
`http://localhost:8000/admin/`.

---

## 6. Frontend Setup

```bash
cd frontend

npm install

copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux

npm run dev
```

The app runs at `http://localhost:5173/` and talks to the API at the URL set
in `VITE_API_BASE_URL`. The frontend is unchanged by the Redis/Celery →
Supabase/Cron migration — it only talks to the same REST endpoints as before.

---

## 7. Environment Variables

### backend/.env

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key — generate a real random value for anything beyond local dev |
| `DEBUG` | `True` for local development |
| `ALLOWED_HOSTS` | Comma-separated hostnames Django will serve |
| `DATABASE_URL` | Supabase PostgreSQL connection string, e.g. `postgresql://postgres:PASSWORD@HOST:5432/postgres` |
| `BREVO_API_KEY` | From your Brevo dashboard (see section 9) |
| `BREVO_WEBHOOK_SECRET` | Shared secret you choose; configured on both sides (see section 10) |
| `BREVO_SENDER_NAME` / `BREVO_SENDER_EMAIL` | Default sender identity |
| `FRONTEND_URL` | Used for CORS/CSRF trusted origins |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins allowed to call the API |
| `TIME_ZONE` | Django's default display timezone (data is always stored in UTC) |

There is no `REDIS_URL`, `CELERY_BROKER_URL`, or `CELERY_RESULT_BACKEND` —
those were removed along with Redis/Celery.

### frontend/.env

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Base URL of the backend API, e.g. `http://localhost:8000/api` |

**Never commit a real `.env` file.** Only `.env.example` files are tracked.

---

## 8. Brevo API Setup

```
Brevo Dashboard → Settings → SMTP & API → API Keys → Generate a new API key
      ↓
Copy the key into backend/.env as BREVO_API_KEY
      ↓
Django's brevo/client.py reads it from settings.BREVO_API_KEY
      ↓
All outbound sends (test emails, campaign sends) go through the Brevo API
```

The platform uses Brevo's transactional email endpoint (`/smtp/email`) for
both test sends and per-recipient campaign delivery, which keeps this
project's own `CampaignRecipient` records as the single source of truth for
delivery status. The API key is only ever read server-side — it is never
sent to or exposed in the React frontend.

---

## 9. Brevo Webhook Setup

```
Brevo Dashboard → Transactional → Settings → Webhooks → Add a new webhook
      ↓
URL: https://YOUR-PUBLICLY-REACHABLE-DOMAIN/api/brevo/webhook/
      ↓
Events to enable: delivered, opened, click, hard_bounce, soft_bounce,
                   blocked, spam, unsubscribed
```

Webhook events are processed **synchronously** in the request/response cycle
of that endpoint (there's no task queue to hand them off to — this was true
even before the Redis/Celery removal).

Brevo does not support HMAC request signing on all plans, so this project
authorizes webhook calls with a **shared secret** instead: set
`BREVO_WEBHOOK_SECRET` in `backend/.env`, then either:

- add a custom header `X-Webhook-Secret: <same value>` to the webhook config
  in Brevo (if your plan supports custom headers), or
- append it as a query parameter: `.../api/brevo/webhook/?secret=<same value>`

**Localhost is not directly reachable by Brevo.** For local testing, expose
your local server with a tunnel such as `ngrok http 8000` or `cloudflared
tunnel`, and use the resulting HTTPS URL as the webhook endpoint. Without a
configured secret, the webhook only accepts requests while `DEBUG=True`
(local development only) — never rely on that in anything resembling
production.

---

## 10. Send Now

Preserved exactly as before, just synchronous instead of task-queued:

```
POST /api/campaigns/{id}/send-now/
      ↓
campaigns.services.send_campaign_now(campaign)
      ↓
brevo/services.py → brevo/client.py → Brevo API (per recipient)
      ↓
Campaign + CampaignRecipient statuses updated; response returns once done
```

Because there's no background worker, the HTTP request for "Send Now" blocks
until every recipient has been attempted. For an MVP-sized contact list this
is fine; if you outgrow it, "Send Now" is the only caller in a request/
response path (scheduled sends already run out-of-band via cron — see below).

---

## 11. Scheduled Campaigns (Cron)

Scheduling no longer uses Celery ETA/Beat. Instead:

```
python manage.py process_scheduled_campaigns
```

is a plain Django management command that:

1. Finds `ScheduledCampaign` rows with status `scheduled` whose `scheduled_at`
   (always stored in UTC) has passed.
2. Claims one at a time using `SELECT ... FOR UPDATE SKIP LOCKED` inside a
   transaction — safe even if cron invokes the command again while a
   previous run is still in progress, or if multiple app instances run cron
   concurrently. A schedule can never be claimed twice.
3. Calls the exact same `campaigns.services.send_campaign_now()` function
   that "Send Now" uses.
4. Marks the schedule `completed` or `failed`, and updates the campaign and
   its recipients' statuses along the way (same statuses the rest of the app
   already used before this migration).

Run it manually any time to process due campaigns immediately:

```bash
cd backend
python manage.py process_scheduled_campaigns
```

### Production cron setup

```
* * * * * cd /path/to/backend && /path/to/venv/bin/python manage.py process_scheduled_campaigns >> /var/log/campaign-cron.log 2>&1
```

Running it every minute is the intended cadence — the command is safe to run
that often and safe to run concurrently with itself.

---

## 12. Timezone Handling

Unchanged from before: `ScheduledCampaign.scheduled_at` is always stored
normalized to UTC (`USE_TZ=True`); the timezone the user picked at scheduling
time is stored separately (`ScheduledCampaign.timezone`) purely for display.
`process_scheduled_campaigns` compares `scheduled_at` (UTC) against
`timezone.now()` (also UTC) — the same comparison Celery's ETA-based
scheduling used to do — so no timezone-handling behavior changed.

---

## 13. Duplicate-Send Protection

Because cron replaces a task queue, this needed real database-level
protection rather than in-memory locking (which wouldn't survive multiple
processes/instances):

- **Schedule-level**: `process_scheduled_campaigns` claims each due
  `ScheduledCampaign` with `SELECT ... FOR UPDATE SKIP LOCKED` and flips its
  status to `processing` inside the same transaction, before any Brevo call
  is made. A second concurrent cron run either skips the locked row (on
  Postgres/Supabase) or sees `status != scheduled` once its own lock
  attempt succeeds — either way, it moves on without resending.
- **Campaign-level**: `send_campaign_now()` itself locks the `Campaign` row
  (`select_for_update()`) before validating and flipping it to `processing`,
  so "Send Now" and a cron-triggered send can never race on the same
  campaign either.
- **Recipient-level**: `CampaignRecipient` rows are only created once
  (`build_recipient_snapshot()` is idempotent) and only `pending` recipients
  are ever sent to — a recipient already `sent`/`failed` is never resent.

`SELECT ... FOR UPDATE SKIP LOCKED` requires Postgres (Supabase uses
Postgres, so production is covered); on SQLite it degrades to a plain row
lock, which is sufficient for local development and the test suite (single
process, no real concurrency).

---

## 14. Health Check

```
GET /api/health/
```

```json
{
    "status": "healthy",
    "database": "connected"
}
```

Only the database is checked — there is no Redis to report on.

---

## 15. Database Migrations

Migrations are already included in this repository. To (re)apply them:

```bash
python manage.py makemigrations
python manage.py migrate
```

---

## 16. Seed Data

```bash
python manage.py seed_data
```

Creates:

- Demo admin user — **username `admin`, password `Admin@12345`** (also usable
  via email `admin@example.com`)
- A demo contact list with 5 sample contacts
- A demo email template
- A demo draft campaign

Log in with the demo credentials on the frontend's login page, or at
`/admin/` for the Django admin.

---

## 17. Testing

```bash
cd backend
python manage.py test
```

All Brevo API calls are mocked in tests (`unittest.mock.patch` on
`brevo.client.BrevoClient`) — the test suite never makes real network calls
to Brevo. Since campaign sending is now synchronous, tests don't need any
task-queue eager-mode shims either — calling `send_campaign_now()` or the
`process_scheduled_campaigns` command in a test simply runs the same code
path production uses.

---

## 18. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `django.db.utils.OperationalError` on startup | Supabase `DATABASE_URL` is wrong, or your Supabase project is paused (free-tier projects pause after inactivity) |
| Scheduled campaigns never send | Cron isn't actually configured/running `process_scheduled_campaigns`, or it's erroring — check its log output |
| A campaign seems stuck in "processing" | `process_scheduled_campaigns` or the "Send Now" request was interrupted mid-send (e.g. process killed). Re-running "Send Now" (or the cron command, for a scheduled campaign whose schedule row is still `processing`) is safe — recipient-level tracking means already-sent recipients are never resent. |
| Webhook events don't update analytics | Webhook URL isn't publicly reachable, or `BREVO_WEBHOOK_SECRET` mismatch |
| `GET /api/health/` reports `degraded` | Supabase database is unreachable — check `DATABASE_URL` and that the project isn't paused |
| CORS errors in the browser console | `CORS_ALLOWED_ORIGINS` in backend `.env` doesn't include the frontend's origin |
| 401 errors after ~30 minutes of use | Expected — access tokens expire; the frontend auto-refreshes using the refresh token. If refresh also fails, log in again. |

---

## 19. Production Deployment Considerations

- Set `DEBUG=False` and a strong, unique `SECRET_KEY`.
- Set `ALLOWED_HOSTS` to your real domain(s).
- Serve over HTTPS; set `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE`, and `SECURE_HSTS_SECONDS` in `settings.py`.
- Use Supabase's connection-pooling host/port for `DATABASE_URL` if you
  expect meaningful concurrent traffic.
- Run the Django app behind a real WSGI/ASGI server (gunicorn/uvicorn) and a
  reverse proxy (nginx), not `manage.py runserver`.
- Configure cron (or your platform's scheduled-job equivalent — e.g. a
  Render/Railway/Heroku Scheduler add-on, a Kubernetes CronJob, or a plain
  crontab entry on a VM) to run `process_scheduled_campaigns` every minute.
  Nothing else needs to run in the background — there is no separate worker
  process to deploy or supervise.
- Serve the frontend's `npm run build` output (`frontend/dist/`) via a static
  file host or CDN, and point `VITE_API_BASE_URL` at your real API domain at
  build time.
- Rotate the Brevo API key and webhook secret out of any shared `.env`
  history; use your platform's secret manager.
- Configure real domain authentication (SPF/DKIM/DMARC) for your sending
  domain in Brevo to maximize deliverability.

---

## 20. Why No Task Queue? (And When You'd Add One Back)

This architecture intentionally trades "send now" being a single blocking
HTTP request (and scheduled sends running once a minute rather than to-the-
second) for removing an entire class of infrastructure: no Redis to run,
patch, or monitor; no worker process to deploy, scale, or restart on
crashes; no broker connection to lose. For an MVP-stage campaign platform
sending to modest-sized lists, that's a good trade.

The natural point to reconsider it is if either becomes true: campaign sizes
grow large enough that a single "Send Now" HTTP request risks timing out, or
you need sub-minute scheduling precision. If that happens, `campaigns.
services.send_campaign_now()` is already the single choke point both entry
paths call — reintroducing a queue would mean changing what's inside that
one function (or splitting recipient sends into batches it enqueues) rather
than restructuring the two callers.

---

## Project Structure

```
email-campaign-platform/
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── config/                # settings, urls, wsgi/asgi
│   ├── accounts/              # auth (JWT register/login/logout/refresh/me)
│   ├── contacts/              # Contact, ContactList, CSV import, Suppression
│   ├── email_templates/       # EmailTemplate CRUD + preview/duplicate
│   ├── campaigns/             # Campaign, CampaignRecipient, synchronous send logic
│   ├── scheduling/            # ScheduledCampaign, validation, process_scheduled_campaigns command
│   ├── brevo/                 # Brevo HTTP client, service layer, webhook handling
│   ├── analytics/             # CampaignEvent, dashboard/campaign stats
│   └── common/                 # shared base model, pagination, exceptions, health check, seed_data
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── components/        # Modal, ConfirmDialog, StatusBadge, DateTimeTimezonePicker, etc.
│       ├── pages/              # Login, Dashboard, Contacts, Templates, Campaigns, Scheduled, Analytics, Settings
│       ├── layouts/             # DashboardLayout (sidebar + top bar)
│       ├── services/            # axios API client + one module per domain
│       ├── context/             # AuthContext, ToastContext
│       ├── utils/                # timezone conversion helpers
│       ├── App.jsx
│       └── main.jsx
│
├── README.md
└── start-dev.md
```

---

## Quick Reference: Setup Commands

```bash
# Backend
cd backend
python -m venv venv && venv\Scripts\activate   # or: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit it with your Supabase DATABASE_URL etc.
python manage.py migrate
python manage.py seed_data
python manage.py runserver

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env
npm run dev

# Process due scheduled campaigns (run manually, or on a cron schedule in production)
cd backend && python manage.py process_scheduled_campaigns

# Tests
cd backend && python manage.py test
```

Demo login: **`admin` / `Admin@12345`**
