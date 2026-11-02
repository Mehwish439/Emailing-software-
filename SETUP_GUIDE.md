# Setup Guide — Email Campaign Platform

Related documents: [`LOGIN_GUIDE.md`](LOGIN_GUIDE.md) (how to sign up / sign in / which dashboard) · [`docs/UPGRADE_NOTES.md`](docs/UPGRADE_NOTES.md) (what changed, test results, limitations) ·
[`deployment/self-hosted-smtp/README.md`](deployment/self-hosted-smtp/README.md) (SMTP server) ·
[`docs/RENDER_DEPLOY.md`](docs/RENDER_DEPLOY.md) (Render deployment detail) · [`README.md`](README.md).

> **Honesty note.** Everything below was written from the source in this repository. Commands marked
> **[local-tested]** were executed while preparing this guide. Anything marked **[needs your infrastructure]**
> (real Brevo account, real SMTP server, DNS, Render, Supabase) has *not* been executed by the author and must be
> verified by you. See §10.12 for the checklist.

---

## 10.1 Architecture and prerequisites

```
Browser (React + Vite SPA)
   │  HTTPS, JWT bearer token (SimpleJWT)
   ▼
Django REST Framework API  ──►  PostgreSQL (Supabase or local)
   │          │
   │          ├─► Brevo transactional API   (default provider)
   │          └─► Self-hosted Postfix/OpenDKIM over authenticated SMTP (optional, explicit)
   ▲
   ├── Brevo webhook      POST /api/brevo/webhook/         (shared secret)
   ├── SMTP bounce intake POST /api/providers/smtp/bounce/ (HMAC-signed)
   └── Scheduler          POST /api/scheduling/process-due/ or `manage.py process_scheduled_campaigns`
```

| Layer | Facts (from the code) |
|---|---|
| Backend | `backend/` — Django 5.1, DRF 3.15, SimpleJWT, django-cors-headers, whitenoise, gunicorn. Python **3.12** (`backend/.python-version`: 3.12.10) |
| Frontend | `frontend/` — React 18, Vite 5, Tailwind 3, react-router 6, axios, recharts. Node **18+** (built here with a current LTS) |
| Database | PostgreSQL (Supabase in production). `DATABASE_URL` is read with `dj-database-url`. SQLite works for quick local runs/tests, **but concurrency tests need PostgreSQL** |
| Auth | Email/username + password → JWT access + refresh. Refresh tokens are blacklisted on logout. Invitation/reset links are signed, single-use, 7-day |
| Roles (actual) | `user`, `company_admin` (must belong to a company), `super_admin` (platform). Role, company and quotas are **read-only** to the user themselves |
| Tenancy | Platform → Company (Plan, status, quota overrides, allowed providers) → User → Campaign. Users with no company ("standalone") keep legacy behaviour: **no quota = unlimited** |
| Providers | `providers/` — `BrevoProvider` (default) and `SmtpProvider`; provider is **frozen per campaign** at claim time; **no silent failover** |
| Scheduler | cron-driven (`process_scheduled_campaigns` command or the secret-protected HTTP endpoint). Celery + Redis are **optional** (blank `CELERY_BROKER_URL` = cron only) |
| Dashboards | User (`/dashboard`…), Company admin (`/company/*`), Platform admin (`/platform/*`) — role-based redirect after login |

**Accounts you need:** Supabase (or any PostgreSQL), Brevo (API key + verified sender/domain), a Render account
(or any host) for production; for self-hosted SMTP also a VPS whose provider permits outbound port 25 and bulk mail, a domain and DNS access.

## 10.2 Installation on Windows (PowerShell)

```powershell
git clone <YOUR-REPO-URL> email-campaign-platform
cd email-campaign-platform

# --- backend ---
cd backend
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env          # then EDIT .env (see §10.4/10.7). Never commit it.
python manage.py migrate
python manage.py createsuperuser     # Django admin account (see §10.6 to make a *platform* admin)
python manage.py runserver           # http://localhost:8000

# --- frontend (second terminal) ---
cd ..\frontend
npm install
Copy-Item .env.example .env          # VITE_API_BASE_URL=http://localhost:8000/api
npm run dev                          # http://localhost:5173

# --- checks ---
cd ..\backend;  python manage.py check; python manage.py makemigrations --check --dry-run; python manage.py test
cd ..\frontend; npm run lint; npm run build
```

## 10.3 Installation on Ubuntu/Linux

**Development**

```bash
sudo apt update && sudo apt install -y git python3.12 python3.12-venv python3-dev libpq-dev build-essential curl
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
git clone <YOUR-REPO-URL> email-campaign-platform && cd email-campaign-platform

cd backend && python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env && nano .env
python manage.py migrate && python manage.py createsuperuser
python manage.py runserver

# new terminal
cd frontend && npm install && cp .env.example .env && npm run dev
```

**Production (generic VPS, if not using Render)** — **[needs your infrastructure]**: run gunicorn
(`gunicorn config.wsgi:application --workers 2 --threads 2 --worker-class gthread --timeout 30`) behind nginx with TLS,
`python manage.py collectstatic --noinput`, `python manage.py migrate`, serve `frontend/dist` as static files with an
`index.html` fallback for unknown paths (the SPA has deep links such as `/accept-invite`, `/company`, `/platform`),
and add the scheduler cron line from §10.9.

## 10.4 Database configuration

* **Supabase:** Project → Settings → Database → connection string. Use the *pooler* string for the web app; the direct
  string for one-off `migrate` if the pooler rejects it. Put it in `backend/.env` as `DATABASE_URL=postgres://USER:PASSWORD@HOST:PORT/DB`.
  SSL is required by Supabase; append `?sslmode=require` if your driver does not negotiate it.
  The app uses short transactions and works with pgbouncer transaction mode; do not add session-level advisory locks.
* **Local PostgreSQL:**
  ```bash
  sudo -u postgres psql -c "CREATE USER campaign_user WITH PASSWORD 'choose-a-password';"
  sudo -u postgres psql -c "CREATE DATABASE email_campaign_db OWNER campaign_user;"
  # DATABASE_URL=postgres://campaign_user:choose-a-password@localhost:5432/email_campaign_db
  ```
* **Test the connection:** `python manage.py check --database default` then `python manage.py showmigrations`.
* **Migrations:** `python manage.py migrate`. This upgrade adds only additive migrations (`tenancy.0001`, `providers.0001`,
  `accounts.0002`, `campaigns.0004`, `contacts.0004` — the last is a choices-only change, no SQL column change).
  `makemigrations --check` must report *No changes detected*.
* **Backup / restore:** `pg_dump --format=custom --no-owner "$DATABASE_URL" > backup.dump` and
  `pg_restore --no-owner --clean --dbname "$TARGET_URL" backup.dump`. Test a restore into a scratch database before you need it. Dumps contain customer data — never put them in the repository or ZIP.
* **Troubleshooting:** see §10.11.

## 10.5 Frontend configuration

| Variable | Frontend-safe? | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | Yes (public) | Base URL of the API **including `/api`**, e.g. `https://your-api.example.com/api`. Default `http://localhost:8000/api` |

That is the **only** Vite variable. Anything starting with `VITE_` is embedded in the browser bundle — **never** put API keys, passwords or secrets there.

* Dev server `npm run dev` (port 5173) · production build `npm run build` → `frontend/dist`.
* **Auth:** tokens are stored in `localStorage`; 401 triggers one refresh attempt, then redirects to `/login?expired=1`.
  A real permission denial (403) does **not** log the user out.
* **Role routing:** after login `super_admin → /platform`, `company_admin → /company`, others → `/dashboard`. Route guards are UX only; every API call is authorised by the backend.
* **CORS:** the backend must list the frontend origin in `CORS_ALLOWED_ORIGINS` (exact scheme+host, no trailing slash). Browser error "blocked by CORS policy" = origin mismatch.
* **Connectivity:** "Cannot reach the server" in the UI = wrong `VITE_API_BASE_URL`, backend down, or CORS. Check `curl <API>/health/`.

## 10.6 Initial company and account setup

1. **Create the first platform admin** (there is deliberately no public path to this role) **[local-tested]**:
   ```bash
   python manage.py shell -c "from django.contrib.auth import get_user_model as g; u=g().objects.get(email='you@example.com'); u.role='super_admin'; u.save()"
   ```
   (Register the account first via the UI or `createsuperuser`.)
2. Sign in → you land on **Platform → Plans & quotas**. Create a plan (daily/monthly quota, seats).
3. **Platform → Companies → New company**, choose the plan. Quota overrides are optional (blank = use the plan).
4. Open the company → **Invite administrator / user** (role *Company admin*). If Brevo is configured the invitation is emailed; **otherwise the single-use link is shown once** for you to pass on.
5. The invitee opens `/accept-invite?token=…`, sets a password, signs in and lands on **/company**.
6. Company admin → **Members & invitations** to invite users with optional per-user quotas (sub-limits inside the company allowance). **Resend invite** is available while an invitation is pending.
7. Verify isolation: sign in as an admin of company A and confirm company B's members/campaigns are not visible; direct API calls to B's ids return 404 (covered by automated tests, §10.12).

Self-service **company sign-up** (`/signup`) creates a company on the limited Trial plan and its Company Admin (`ALLOW_COMPANY_SIGNUP`, `TRIAL_*`). The legacy standalone sign-up API (`/api/auth/register/`, unlimited, no company) is no longer linked from the UI; disable it with `ALLOW_PUBLIC_REGISTRATION=False`. See [`LOGIN_GUIDE.md`](LOGIN_GUIDE.md).

## 10.7 Brevo setup — **[needs your Brevo account]**

1. Brevo → SMTP & API → create an API key → `BREVO_API_KEY` (backend only).
2. Verify the sender address/domain in Brevo (add its SPF/DKIM DNS records) and set `BREVO_SENDER_NAME`, `BREVO_SENDER_EMAIL`.
3. Webhook: Brevo → Transactional → Settings → Webhooks → URL `https://<API>/api/brevo/webhook/`, events delivered/opened/clicked/soft_bounce/hard_bounce/blocked/spam/unsubscribed/invalid_email. Authenticate with header `X-Webhook-Secret: <BREVO_WEBHOOK_SECRET>` (preferred) — the `?secret=` query form also works but secrets in URLs end up in access logs.
4. Test with a **small controlled list you own** — never a bulk campaign. Send to two addresses, confirm status moves *queued → accepted → delivered* only when Brevo's delivered event arrives.
5. Bounce/unsubscribe tests: send to Brevo's documented test addresses or an address you control that you then bounce/unsubscribe; confirm a Suppression row appears.
6. Rate limits: Brevo plan limits apply; set `Platform → Providers & limits → Rate/minute` below them. A 429/5xx from Brevo is treated as temporary and retried; ambiguous timeouts are **not** blindly resent.

## 10.8 Self-hosted SMTP setup — **[needs a real server, DNS and hosting approval]**

Authoritative instructions: [`deployment/self-hosted-smtp/README.md`](deployment/self-hosted-smtp/README.md). Files: `setup-smtp.sh`, `configure-postfix.sh`, `configure-opendkim.sh`, `firewall-setup.sh`, `add-sending-domain.sh`, `validate-smtp.sh`, `health-check.sh`, `activate-production.sh`, `backup-config.sh`, `bounce-forwarder.py`, `requirements.env.example`, `dns-records.example.txt`, `security-checklist.md`, `troubleshooting.md`.

Order: **(0)** written hosting approval for port 25 + bulk mail → **(1)** `sudo ./setup-smtp.sh` (mail is *held*) → **(2)** publish DNS (A, PTR/rDNS at the host, SPF, DKIM, DMARC, MX for the bounce domain) then `sudo ./validate-smtp.sh dns` and `all` → **(3)** `sudo ./activate-production.sh` (explicit confirmation; reverse with `--deactivate`).

Application side (backend env): `SMTP_HOST`, `SMTP_PORT` (587 STARTTLS, or 465 with `SMTP_USE_SSL`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_BOUNCE_DOMAIN`, `SMTP_BOUNCE_WEBHOOK_SECRET` (the forwarder signs bounces with it). Then **Platform → Providers & limits**: *Test SMTP connection* (connects and authenticates; sends **no** mail) and only then change the active provider (confirmation required).

**Delivery semantics:** `accepted` = the SMTP server took the message — **not** proof of inbox delivery. SMTP has no delivery receipt; only bounces/complaints come back. An ambiguous result (timeout after DATA) goes to **needs review** and is never auto-resent.

## 10.9 Campaign scheduling and operations

* **Flow:** create campaign → start now or schedule → credits (1 per recipient) are **reserved atomically** at start → each recipient becomes an `OutboundMessage` with a unique idempotency key → provider (frozen) → events.
* **Scheduler** (pick one, both are safe together thanks to row locks):
  * cron: `* * * * * cd /path/backend && /path/venv/bin/python manage.py process_scheduled_campaigns >> /var/log/campaign-cron.log 2>&1`
  * HTTP: `POST https://<API>/api/scheduling/process-due/` with header `X-Cron-Secret: <CRON_SECRET>` (cron-job.org, GitHub Actions, or Supabase pg_cron — see `docs/supabase_cron_setup.sql`). Without `CRON_SECRET` the endpoint refuses unless `DEBUG=True`.
  * optional Celery: set `CELERY_BROKER_URL` (Redis) and run worker + beat; cron keeps working alongside.
* **Quota rules (actual behaviour):** credits are *reserved* at claim, *consumed* when a provider accepts, *released* if the message is never submitted (late suppression, permanent failure, failed/cancelled campaign). Retries reuse the same ledger row (no double charge). Over-limit → HTTP 400 and the whole claim rolls back.
* **Failed / uncertain sends:** Platform → **Queue & failures**. *Retry* only for failed messages with a temporary error. For *needs review* choose **Was sent** only with provider-log proof, **Resend** only after confirming it was not accepted.
* **Bounces:** hard bounce / complaint / unsubscribe → suppress immediately. Soft bounces → suppress after `SOFT_BOUNCE_SUPPRESS_THRESHOLD` (default 3) **consecutive** soft bounces within `SOFT_BOUNCE_WINDOW_DAYS` (default 30); a delivered event resets the streak; `0` disables. Duplicate events are ignored (idempotent).
* **Monitoring:** Platform → **System health** shows DB, providers, job heartbeats (stale > 10 min) and alerts.

## 10.10 Production deployment

Existing, documented target: **Render** (backend web service + static frontend) with **Supabase** PostgreSQL — see `render.yaml` and `docs/RENDER_DEPLOY.md`.

| Item | Setting |
|---|---|
| Backend env | `SECRET_KEY` (random; the app **refuses to start** with `DEBUG=False` and the dev key), `DEBUG=False`, `DATABASE_URL`, `BREVO_*`, `CRON_SECRET`, `FRONTEND_URL`, `BACKEND_BASE_URL`, `CORS_ALLOWED_ORIGINS`, `TIME_ZONE` |
| Frontend env | `VITE_API_BASE_URL` only |
| HTTPS | terminated at Render; `SECURE_PROXY_SSL_HEADER` is set; cookies are secure when `DEBUG=False` |
| HSTS / SSL redirect | **Deployment decisions** (`SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, both default off). Enable once HTTPS is verified |
| SPA routing | `render.yaml` now contains a rewrite `/* → /index.html` so `/accept-invite`, `/company`, `/platform` survive a refresh |
| Migrations | `python manage.py migrate` on each release (Render pre-deploy/start step — **confirm yours**) |
| Scheduler | §10.9 (**decision required**: pg_cron vs external cron vs Celery) |
| Health check | `GET /api/health/` |
| Backups / rollback | `pg_dump` schedule (**decision required**); rollback = redeploy previous commit (new columns are ignored by old code) |

Changing `SECRET_KEY` invalidates existing JWTs (everyone signs in again) and outstanding invitation links.

## 10.11 Troubleshooting

| Symptom | Likely cause | Diagnose | Fix |
|---|---|---|---|
| `connection refused` / `could not translate host` | wrong/empty `DATABASE_URL`, DB down | `python manage.py check --database default` | fix URL; Supabase needs SSL |
| `ImproperlyConfigured: SECRET_KEY…` | `DEBUG=False` without `SECRET_KEY` | env | set a long random key |
| `Missing env var` / Brevo "not configured" | `.env` not loaded | `Platform → System health` | set vars, restart |
| Migration conflict / "No changes detected" fails | model drift or parallel branches | `makemigrations --check --dry-run`, `showmigrations` | merge migrations; never edit applied ones |
| UI: "Cannot reach the server" | wrong `VITE_API_BASE_URL`, backend down | `curl $API/health/` | fix URL / start backend |
| Browser CORS error | origin not in `CORS_ALLOWED_ORIGINS` | DevTools → Network | add exact origin, restart |
| Login loops to `/login?expired=1` | expired refresh / changed `SECRET_KEY` | clear storage | sign in again |
| React "Objects are not valid as a React child" | raw API error object rendered | — | fixed: all errors go through `utils/formatError.js`; use `formatApiError(err)` in new code |
| Deep link 404 on refresh | host lacks SPA fallback | open `/company` directly | add rewrite to `index.html` |
| Brevo 401/403 | bad/IP-restricted key | health page | rotate key; check Brevo IP allow-list |
| Webhook 401 | secret mismatch | server log "webhook rejected" | same value in Brevo header and `BREVO_WEBHOOK_SECRET` |
| Scheduled campaign never starts | no cron call / wrong secret | health → job heartbeats stale; log "process-due: REJECTED" | fix scheduler, `CRON_SECRET` |
| HTTP 400 "exceeds quota" | user/company/platform limit | Company → Quotas / Platform → Plans | raise limit or wait for reset |
| SMTP auth/TLS failure | wrong creds, cert, port | `validate-smtp.sh all`, `openssl s_client -starttls smtp -connect host:587` | fix creds/cert |
| DNS/PTR problems | rDNS not set | `validate-smtp.sh dns`, `dig -x IP` | set PTR at hosting provider |
| Port 25 blocked | provider policy | `validate-smtp.sh` port check | request unblock in writing or use a relay |
| Mail stuck in queue | deferred by remote, DNS, block | `postqueue -p`, `journalctl -u postfix` | fix cause; `postqueue -f` |
| Bounces not appearing | forwarder down / bad HMAC | `systemctl status` of bounce forwarder; server log "bad signature" | match `SMTP_BOUNCE_WEBHOOK_SECRET` |
| Message in *needs review* | ambiguous send result | Platform → Queue | resolve with provider-log evidence; **never** blind resend |

## 10.12 Testing and maintenance

```bash
cd backend && python manage.py test                       # whole suite (SQLite or PostgreSQL)
DATABASE_URL=postgres://… python manage.py test providers.tests_concurrency   # PostgreSQL-only concurrency tests
python manage.py test tenancy        # roles, tenant isolation, admin APIs, invitations, quotas
python manage.py test providers      # provider selection, idempotent dispatch, rate limit, bounces (real local SMTP server)
python manage.py test scheduling brevo analytics   # scheduling, webhooks, suppression
cd ../frontend && npm run lint && npm run build
```

* **Maintenance:** rotate secrets (new value → deploy → revoke old); renew TLS certs (certbot timer on the SMTP host; `validate-smtp.sh tls`); update dependencies in a branch and rerun all suites; inspect logs (`journalctl`, Render logs) and the Platform health/queue pages.
* **Local checklist:** `.env` files exist and are git-ignored · migrations applied · tests green · lint/build clean.
* **Staging checklist:** real Brevo test with owned addresses · webhook delivered a real event · invitation emailed and accepted · scheduler calling the endpoint.
* **Production-readiness checklist:** credentials rotated · `DEBUG=False` · HTTPS · CORS exact · backups tested · SMTP validation passed *and* a controlled real-delivery test done · HSTS decision made.
* **Packaging checklist:** no `.env`, keys, `venv`, `node_modules`, dumps, logs · secret scan clean · archive contents listed.
