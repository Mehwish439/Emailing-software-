# Deploying to Render (Free Tier)

This guide deploys the whole platform on Render's free tier: the Django API
as a free Web Service, the React frontend as a free Static Site, Supabase
stays your database (unchanged from local dev), and Brevo stays your email
provider (unchanged).

**Read this first — the free-tier trade-off that shapes everything below:**
Render's free Web Services spin down after ~15 minutes of no traffic and
take 30–60+ seconds to cold-start on the next request. That affects two
things here: Brevo's webhook can time out calling a sleeping service, and
there's no reliable free way to run traditional cron on Render (their Cron
Jobs product is a paid feature, and pricing/free-tier terms can change — 
check [render.com/pricing](https://render.com/pricing) yourself before
committing). This guide's answer to both problems is the same: a **free
external scheduler** (cron-job.org or similar) hitting a secret-protected
HTTP endpoint every minute. That both processes due scheduled campaigns
*and* keeps your web service warm, which incidentally also makes the
webhook far more reliable. See section 5.

---

## 1. Prerequisites

- This project pushed to a GitHub (or GitLab) repository
- A [Render](https://render.com) account (free)
- Your Supabase `DATABASE_URL` (see the main README, section 4)
- Your Brevo `BREVO_API_KEY` and a `BREVO_WEBHOOK_SECRET` you choose yourself

---

## 2. Deploy the backend (Django) — Web Service

In the Render dashboard: **New → Web Service** → connect your repo.

| Setting | Value |
|---|---|
| Name | `<your-project>-backend` (Render generates your URL from this, e.g. `<name>.onrender.com`) |
| Root Directory | `backend` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Start Command | `gunicorn config.wsgi:application` |
| Instance Type | Free |

### Environment variables (Web Service → Environment tab)

| Key | Value |
|---|---|
| `SECRET_KEY` | Generate one, e.g. `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `<your-backend-name>.onrender.com` |
| `DATABASE_URL` | Your Supabase connection string |
| `BREVO_API_KEY` | Your Brevo API key |
| `BREVO_WEBHOOK_SECRET` | A secret you make up (save it — you'll need it in section 4 and again in Brevo) |
| `BREVO_SENDER_NAME` | Your sender name |
| `BREVO_SENDER_EMAIL` | Your verified sender email |
| `BACKEND_BASE_URL` | `https://<your-backend-name>.onrender.com` (used to build the unsubscribe links embedded in sent emails — get this right or unsubscribe links will be broken) |
| `FRONTEND_URL` | `https://<your-frontend-name>.onrender.com` (set after step 3, once you know it) |
| `CORS_ALLOWED_ORIGINS` | Same as `FRONTEND_URL` |
| `TIME_ZONE` | e.g. `Asia/Karachi` |
| `CRON_SECRET` | Another secret you make up (needed for section 5) |

Deploy. First deploy will fail to serve real traffic correctly until
migrations run — that's expected, continue to the next step.

### Run migrations + seed data

Render's Web Service dashboard has a **Shell** tab once the service is
live. Open it and run:

```bash
python manage.py migrate
python manage.py seed_data
```

(Re-run `migrate` after any future deploy that includes new migrations —
Render doesn't do this automatically unless you add it to the build
command, which is also a valid option: append `&& python manage.py
migrate` to the Build Command above if you'd rather it happen on every
deploy automatically.)

---

## 3. Deploy the frontend (React) — Static Site

**New → Static Site** → same repo.

| Setting | Value |
|---|---|
| Name | `<your-project>-frontend` |
| Root Directory | `frontend` |
| Build Command | `npm install && npm run build` |
| Publish Directory | `dist` |

### Environment variable

| Key | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://<your-backend-name>.onrender.com/api` |

Deploy. Once it's live, go back to the backend Web Service's environment
variables and fill in `FRONTEND_URL` / `CORS_ALLOWED_ORIGINS` with this
Static Site's real URL (you needed the frontend's URL to set those, and
needed the backend's URL to set `VITE_API_BASE_URL` — a one-time
chicken-and-egg, resolved by circling back). Redeploy the backend after
updating those two.

---

## 4. Configure the Brevo webhook

Brevo Dashboard → Transactional → Settings → Webhooks → Add a new webhook:

```
URL: https://<your-backend-name>.onrender.com/api/brevo/webhook/
Events: delivered, opened, click, hard_bounce, soft_bounce, blocked, spam, unsubscribed
```

Since Brevo doesn't support HMAC signing on all plans, this project checks
the shared secret you set as `BREVO_WEBHOOK_SECRET` in step 2. Configure it
on the Brevo side as either:
- a custom header `X-Webhook-Secret: <same value>` (if your Brevo plan
  supports custom webhook headers), or
- a query parameter on the URL itself: `.../api/brevo/webhook/?secret=<same value>`

**Cold-start risk:** if your backend has been asleep, this webhook call may
time out before Render finishes waking it up, silently losing that event.
Section 5's keep-alive ping substantially reduces how often your service is
actually asleep when Brevo calls in.

---

## 5. Scheduled campaigns + keeping the service warm (the free-tier trick)

There is no cron here — that's `python manage.py process_scheduled_campaigns`
run on a timer locally, but Render's free tier has no reliable free way to
run that command on a schedule directly. Instead, this project exposes the
exact same logic as an HTTP endpoint:

```
POST /api/scheduling/process-due/
```

protected by the `CRON_SECRET` you set in step 2, sent as either an
`X-Cron-Secret` header or a `?secret=` query parameter. It's safe to call
this every minute, repeatedly, or even concurrently with itself — see the
row-locking explained in `scheduling/services.py`.

Something needs to actually call it once a minute. **Recommended: use
Supabase's own `pg_cron` + `pg_net` extensions** — since Supabase is
already your database, this needs no third-party account at all, and
Postgres-native scheduling hits the minute mark more reliably than most
free external schedulers.

### Recommended: pg_cron + pg_net (all inside Supabase)

`pg_cron` schedules jobs directly in Postgres; `pg_net` lets a Postgres job
make an outbound HTTP call. Together, Supabase itself becomes the
scheduler — no external service, no separate account, one less moving
part.

A ready-to-run script is included at
[`docs/supabase_cron_setup.sql`](supabase_cron_setup.sql). Short version:

1. Open your Supabase project → **SQL Editor** → New query.
2. Paste in `docs/supabase_cron_setup.sql`, fill in your real backend URL
   and your `CRON_SECRET` value in the two placeholders near the top, and
   run it.
3. That's it — it enables both extensions, stores your URL/secret in
   Supabase Vault (not as plaintext in the cron job itself), and schedules
   a job that POSTs to `/api/scheduling/process-due/` every minute.

The script's comments also cover checking run history
(`cron.job_run_details`), pausing/resuming, unscheduling, and rotating the
stored secret later.

**If `create extension pg_cron` or `pg_net` errors out** — availability can
vary by Supabase plan/project, and terms can change — fall back to the
external scheduler option below instead. The app-side endpoint is
identical either way; only what's calling it differs.

### Fallback: a free external HTTP scheduler

If pg_cron/pg_net aren't available on your project, use any free service
that can hit a URL on an interval. [cron-job.org](https://cron-job.org) is
free and simple:

1. Create an account, add a new cron job.
2. URL: `https://<your-backend-name>.onrender.com/api/scheduling/process-due/`
3. Method: `POST`
4. Add a custom header: `X-Cron-Secret: <your CRON_SECRET value>`
5. Schedule: every 1 minute.

Other free scheduled-HTTP-request services (a GitHub Actions `schedule:`
trigger calling `curl`, for instance) work the same way, though GitHub
Actions' schedule triggers aren't guaranteed to fire exactly on the minute
and can drift under load — fine if near-enough timing is acceptable, less
ideal if it isn't. As with Render's own pricing, double-check whatever free
scheduler you pick still has generous-enough free-tier limits for a
once-a-minute job, since terms do change.

### Why this also fixes the webhook cold-start problem

Whichever option you use, every trigger is a real HTTP request to your
backend, which resets Render's 15-minute inactivity timer — this holds for
pg_net's calls exactly the same as an external pinger's, since Render sees
an ordinary inbound request either way. With a call every minute, your free
Web Service effectively never goes to sleep during the hours it's running,
which means Brevo's webhook calls almost always hit a warm instance instead
of triggering a cold start. Two free-tier problems, one fix.

(One asterisk: `pg_net`'s `http_post` is asynchronous — the SQL statement
queues the request and returns immediately, with a background worker
actually sending it, typically within a few seconds. That's irrelevant to
correctness here since nothing waits on the response, but it's worth
knowing if you're inspecting timing closely.)

### If you ever get real cron access instead

Nothing above is required once you're on infrastructure with actual cron
(a paid Render instance with their Cron Jobs product, a VPS, etc.) — just
run `python manage.py process_scheduled_campaigns` on a `* * * * *`
schedule as described in the main README, and you can stop the pg_cron job
(`select cron.unschedule('process-due-campaigns');`) or the external
scheduler. Leaving it running as a keep-alive/backup is also harmless,
since every path here is safe to run concurrently with any other.

---

## 6. Verify everything

- `https://<your-backend-name>.onrender.com/api/health/` → `{"status": "healthy", "database": "connected"}`
- Frontend loads at `https://<your-frontend-name>.onrender.com`, log in with
  the seeded demo account (`admin` / `Admin@12345`) or register a new one
- Create a campaign, send a test email, confirm it arrives
- In Supabase's SQL Editor, confirm the cron job is actually running:
  ```sql
  select * from cron.job_run_details
  where jobid = (select jobid from cron.job where jobname = 'process-due-campaigns')
  order by start_time desc
  limit 5;
  ```
  You should see rows appearing roughly once a minute with `status = 'succeeded'`.
- Schedule a campaign a couple minutes out, wait, confirm it actually sends
  (check the campaign's status flips to "sent" and its `ScheduledCampaign`
  status flips to "completed")
- Send a real campaign and check that Delivered/Opened update in Analytics
  within a minute or two of opening it (confirms the webhook is reachable)

---

## 7. Costs at a glance

| Piece | Where | Free tier? |
|---|---|---|
| Django API | Render Web Service | Yes (with cold-start sleep) |
| React frontend | Render Static Site | Yes |
| Database | Supabase | Yes (free tier pauses after inactivity too — same caveat applies) |
| Email delivery | Brevo | Yes, within their free sending limits |
| Scheduling trigger | Supabase pg_cron + pg_net (or cron-job.org as fallback) | Yes |

Nothing in this setup requires a paid plan. The trade-offs are cold starts
and Supabase's own free-tier pause-after-inactivity behavior — both fine
for a demo/MVP, both things to revisit (a paid Render instance, Supabase's
paid tier) if this becomes a real production workload.
