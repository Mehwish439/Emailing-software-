-- =============================================================================
-- Supabase pg_cron + pg_net setup: trigger scheduled campaign processing
-- =============================================================================
-- Run this in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query).
--
-- What this does: schedules a Postgres-native cron job (pg_cron) that fires
-- every minute and makes an async HTTP POST (pg_net) to your Render
-- backend's POST /api/scheduling/process-due/ endpoint — the same endpoint
-- an external scheduler like cron-job.org would hit, except now Postgres
-- itself is the scheduler. No third-party service, no separate account.
--
-- Before running: replace the two placeholder values in STEP 2 below with
-- your real backend URL and CRON_SECRET, then run the whole script.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- STEP 1: Enable the required extensions (safe to re-run; no-ops if already on)
-- -----------------------------------------------------------------------------
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- If either of these errors out, your Supabase project/plan may not have
-- that extension available. Check Dashboard -> Database -> Extensions to
-- confirm, and if pg_cron/pg_net truly aren't available on your project,
-- fall back to the free external scheduler (cron-job.org) option in
-- docs/RENDER_DEPLOY.md instead — the app-side endpoint is identical either
-- way, only the thing calling it differs.


-- -----------------------------------------------------------------------------
-- STEP 2: Store your backend URL + cron secret in Supabase Vault
-- -----------------------------------------------------------------------------
-- Using Vault (rather than pasting these values directly into the cron job
-- below) keeps the secret out of plaintext SQL history and the cron.job
-- table. Replace both placeholder values, then run these two lines ONCE —
-- re-running vault.create_secret with the same name will error; use
-- vault.update_secret (see the "rotating" note near the bottom) to change
-- a value later instead.

select vault.create_secret(
  'https://YOUR-BACKEND-NAME.onrender.com/api/scheduling/process-due/',  -- <-- replace with your real Render backend URL
  'campaign_process_due_url',
  'URL for scheduled campaign processing on Render'
);

select vault.create_secret(
  'YOUR_CRON_SECRET_HERE',  -- <-- replace with the same value you set as CRON_SECRET in Render's env vars
  'campaign_cron_secret',
  'Shared secret for triggering scheduled campaign processing'
);


-- -----------------------------------------------------------------------------
-- STEP 3: Schedule the cron job — runs every minute
-- -----------------------------------------------------------------------------
select cron.schedule(
  'process-due-campaigns',   -- job name — used to unschedule/inspect it later
  '* * * * *',               -- every minute (pg_cron's schedule is always in UTC, which doesn't matter here — see note below)
  $$
  select net.http_post(
    url     := (select decrypted_secret from vault.decrypted_secrets where name = 'campaign_process_due_url'),
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Cron-Secret', (select decrypted_secret from vault.decrypted_secrets where name = 'campaign_cron_secret')
    ),
    body    := '{}'::jsonb
  );
  $$
);

-- Note on timezones: pg_cron's own schedule ('* * * * *') runs in UTC, but
-- that only controls *how often this job fires* (every minute, regardless
-- of timezone). It has nothing to do with the timezone a campaign was
-- scheduled in — that's handled correctly inside the Django app itself
-- (ScheduledCampaign.scheduled_at is always stored in UTC; see the main
-- README's Timezone Handling section). This job firing every minute in UTC
-- is exactly equivalent to a `* * * * *` crontab entry anywhere else.


-- =============================================================================
-- Useful follow-up queries
-- =============================================================================

-- Confirm the job is scheduled:
--   select * from cron.job where jobname = 'process-due-campaigns';

-- Check recent run history / troubleshoot failures:
--   select * from cron.job_run_details
--   where jobid = (select jobid from cron.job where jobname = 'process-due-campaigns')
--   order by start_time desc
--   limit 20;

-- Pause the job temporarily without deleting it:
--   select cron.alter_job(
--     (select jobid from cron.job where jobname = 'process-due-campaigns'),
--     active := false
--   );
-- Resume it again:
--   select cron.alter_job(
--     (select jobid from cron.job where jobname = 'process-due-campaigns'),
--     active := true
--   );

-- Remove the job entirely:
--   select cron.unschedule('process-due-campaigns');

-- Rotate a stored secret (e.g. after changing CRON_SECRET in Render) —
-- vault.create_secret errors on a duplicate name, so update instead:
--   select vault.update_secret(
--     (select id from vault.secrets where name = 'campaign_cron_secret'),
--     'YOUR_NEW_CRON_SECRET'
--   );
-- =============================================================================
