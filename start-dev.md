# Local Development — Quick Start

This assumes you already have a Supabase project (see README.md section 4
if not). You'll need **two terminals** for normal development, and
occasionally a third to manually trigger scheduled-campaign processing.

## Terminal 1 — Backend API

```bash
cd backend
python -m venv venv
venv\Scripts\activate          REM Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
copy .env.example .env         REM Windows, then edit it
# cp .env.example .env         # macOS/Linux, then edit it
#   -> set DATABASE_URL to your Supabase connection string
#   -> set BREVO_API_KEY, BREVO_SENDER_NAME, BREVO_SENDER_EMAIL

python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

API available at `http://localhost:8000/`.

## Terminal 2 — Frontend

```bash
cd frontend
npm install
copy .env.example .env         REM Windows
# cp .env.example .env         # macOS/Linux
npm run dev
```

App available at `http://localhost:5173/`. Log in with `admin` /
`Admin@12345`.

## Processing scheduled campaigns locally

There's no worker process to run in the background. In production this runs
via cron once a minute; locally, just run it manually whenever you want to
test a scheduled send:

```bash
cd backend
venv\Scripts\activate          REM Windows
# source venv/bin/activate     # macOS/Linux

python manage.py process_scheduled_campaigns
```

Schedule a campaign for a minute in the future from the UI, wait for it to
become due, then run the command above — it will pick it up and send it
through Brevo. Run it again immediately after; it will report "no due
schedules found" rather than sending anything twice.

If you want it running continuously while you develop (closer to how
production cron behaves), you can loop it in a spare terminal:

```bash
# macOS/Linux
while true; do python manage.py process_scheduled_campaigns; sleep 60; done
```

```powershell
# Windows PowerShell
while ($true) { python manage.py process_scheduled_campaigns; Start-Sleep -Seconds 60 }
```

## Verifying everything is wired up

Visit `http://localhost:8000/api/health/` — you should see:

```json
{"status": "healthy", "database": "connected"}
```

If it shows `degraded`, check that `DATABASE_URL` in `backend/.env` points
at a reachable Supabase database (and that the Supabase project isn't
paused — free-tier projects pause after a period of inactivity).

## Webhook testing (optional, for real Brevo event tracking)

Brevo can't reach `localhost` directly. To test webhook-driven analytics
locally, expose port 8000 with a tunnel:

```bash
ngrok http 8000
```

Then configure the resulting HTTPS URL + `/api/brevo/webhook/` as the
webhook endpoint in your Brevo dashboard, as described in README.md section
9.
