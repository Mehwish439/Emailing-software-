# Upgrade notes — multi-tenant admin, pluggable email providers, self-hosted SMTP

Status: **Phase 1 (backend + SMTP server package) complete and tested. Phase 2 (company-admin and platform-admin dashboards,
invitation flow, error handling) implemented in this revision — see §7. Not production-verified: see §6 and §7.4.**
Login & dashboards: [`../LOGIN_GUIDE.md`](../LOGIN_GUIDE.md) · Setup: [`../SETUP_GUIDE.md`](../SETUP_GUIDE.md) · SMTP server: [`../deployment/self-hosted-smtp/README.md`](../deployment/self-hosted-smtp/README.md)

## 1. What the inspection found (before any change)

* Django 5.1 + DRF + SimpleJWT, React/Vite frontend, PostgreSQL (Supabase), Brevo for all sending.
* **Every** campaign email went through `brevo.services.send_to_recipient`; sends were synchronous batches
  (`CAMPAIGN_SEND_BATCH_SIZE`) resumed by a cron-driven command / `POST /api/scheduling/process-due/`. No Celery/Redis.
* Tenancy was *single-owner*: every record hangs off a `User` (`owner` / `created_by`). No company, role or quota concept.
  `Suppression` is global (unique email) — safe (it only ever blocks sends) but company views must filter it.
* Existing weaknesses closed by this work: no idempotency (a Brevo read-timeout was retried immediately and could
  double-send; a crash between "provider accepted" and "mark sent" would resend on resume), no quota, no rate limit.
* **Pre-existing model/migration drift (not caused by this work):** `campaigns/0002_campaign_segments` created a
  `Campaign.segments` many-to-many that the model no longer declared, so `makemigrations` wanted to **drop** it.
  The field has been restored on the model (matching the deployed schema, no data touched) so no destructive migration exists.
* The uploaded zip contained **real `backend/.env` and `frontend/.env` files** (git-ignored, but in the archive) and a committed root `venv/`.
  They were set aside and are excluded from the deliverable. **Rotate those credentials** (Supabase DB password, Brevo key, JWT/Django secret).
  Also remove the root `venv/` from git history/tracking.

## 2. Architecture

```
Platform (PlatformSettings: budgets, rate, active provider, queue pause)
  └─ Company (Plan, status, quota overrides, allowed providers)
       └─ User (role, daily/monthly quota)            legacy users: company=None, limits NULL = unlimited (unchanged)
            └─ Campaign (provider frozen at first send) ─▶ CampaignRecipient ─▶ OutboundMessage (idempotency key,
                 provider, provider_message_id, state)  ─▶ ratelimit/fair-share ─▶ provider (Brevo | SMTP) ─▶ events
```

* **Providers** (`backend/providers/`): `BaseProvider` → `BrevoProvider` (wraps the unchanged `BrevoClient`) and `SmtpProvider`.
  One shared `builder.build_campaign_email` (merge tags, unsubscribe URL/headers, A/B variant) — *no duplicated campaign logic*.
  Error taxonomy: temporary / permanent / **ambiguous** (outcome unknown → never auto-retried) / config.
* **Idempotent dispatch** (`dispatch.py`): unique key per recipient; lock-and-claim; an ACCEPTED message is never re-sent;
  stale claims and ambiguous results go to **needs_review**; the provider is read from `campaign.provider` (frozen at claim time);
  there is **no silent failover** — a down provider defers messages and raises a health alert; switching is an explicit, audited,
  guarded admin action.
* **Quota** (`tenancy/quota.py`): platform → company → user, daily + monthly, **one credit per recipient message**,
  reserved transactionally at claim time (row locks in fixed order platform→company→user), one ledger row per recipient
  (no double charge on retry), consumed when a provider accepts, released if never submitted (late suppression, permanent
  failure, failed campaign). Over-limit → HTTP 400 and the whole claim rolls back. `reconcile()` repairs drift.
  NULL limit = unlimited. The DB is the source of truth; Redis holds nothing.
* **Rate limit + fairness** (`providers/ratelimit.py`): platform `rate_per_minute` (or `SMTP_RATE_LIMIT`); each company with
  pending work is entitled to rate/N per rolling minute and may *borrow* capacity other active companies are not using.
  A software guard only — it never creates capacity.
* **Delivery states** are kept distinct and honest: queued · submitting · **accepted by provider** · deferred · delivered
  (only from a real delivery event) · bounced · failed · suppressed · cancelled · needs_review. Analytics come only from
  recorded events; rates are `null` (not 0) with no denominator.
* **Bounces** (`providers/bounces.py`): parses DSN (RFC 3464) and ARF complaints, attributes via signed VERP return-path or the
  returned `X-Recipient-Id` headers, ignores "relayed/delivered" notices, and feeds the **same** processor Brevo webhooks use
  (dedupe, suppression, recipient status). HMAC-signed intake `POST /api/providers/smtp/bounce/`.
* **Background jobs**: `config/celery.py` + `providers/tasks.py` (process_due, reconcile_quota, smtp_health, review_stuck) are thin
  wrappers over the same service functions as the cron path; both can run together safely (row locks + idempotency keys).
  Heartbeats feed the Super Admin health page. Celery is optional; blank `CELERY_BROKER_URL` keeps today's cron behaviour.

## 3. New API surface

Company admin (`/api/company/…`, always scoped to the caller's own company; never accepts a company id):
`overview`, `members` (+invite with seat limit, PATCH quotas/role/active, pause/resume a user's campaigns), `quotas`
(allocation, unallocated, over-allocation guard), `campaigns` (+pause/resume), `analytics`, `suppressions`, `audit-log`,
`settings`, `subscription`.
Platform (`/api/platform/…`, super admins only): `overview` (capacity), `companies` (CRUD, suspend/reactivate — new sends
refused, running campaigns **held** not deleted), `users` (deactivate, single-use reset links), `plans` (CRUD, duplicate, archive),
`settings` (budgets, rate, active provider, company provider choice), `quotas` (over-commit report), `queue` (+pause/resume,
messages, retry, resolve needs-review), `campaigns` (+pause/resume/switch-provider), `health`, `audit-log`, `analytics`.
`POST /api/auth/accept-invite/` — invitation/reset links are **single-use** (bound to the password hash) and expire in 7 days.
`/api/auth/me/` now returns `role`, `company` and a `quota` snapshot; role/company/quotas are read-only to the user.

## 4. Migrations (all additive — verified: no RemoveField/DeleteModel/destructive AlterField)

`tenancy.0001` (Plan, Company, PlatformSettings, QuotaLedger, AuditLog, JobHeartbeat) · `providers.0001` (OutboundMessage) ·
`accounts.0002` (User.role/company/daily_quota/monthly_quota — nullable/defaulted) · `campaigns.0004` (Campaign.provider,
Status.PAUSED choice). Existing rows are untouched; existing users behave exactly as before until an admin assigns them to a company.
Run: `python manage.py migrate`. Rollback = redeploy the previous code (new columns are ignored by old code).

To create the first platform admin: `python manage.py shell -c "from django.contrib.auth import get_user_model as g; u=g().objects.get(email='you@x'); u.role='super_admin'; u.save()"`.
To create a company: `/api/platform/companies/`, then set a user's `company` + `role=company_admin` in Django admin/shell (a UI for this belongs to Phase 2).

## 5. Tests

`python manage.py test` — **258 tests, all passing on PostgreSQL 16** (145 pre-existing + 113 new); also green on SQLite
(concurrency tests skip there). New suites: `providers.tests` (real local SMTP server via `aiosmtpd`, dispatch idempotency,
quota, rate limit/fairness, Celery tasks), `providers.tests_bounces`, `providers.tests_concurrency` (real threads on PostgreSQL:
simultaneous campaigns cannot exceed user/company/platform limits; 10 workers send one recipient exactly once; racing resume
jobs never duplicate an email), `tenancy.tests` (permissions, tenant isolation, admin APIs).
Install dev deps: `pip install -r requirements-dev.txt`. Run concurrency tests: `DATABASE_URL=postgres://… python manage.py test providers.tests_concurrency`.

**Bugs found by testing against real components (fixed):** `select_for_update` + nullable `select_related` crashes on PostgreSQL
(SQLite hides it — would have broken every send in production); SMTP bodies were sent with bare-LF endings and 7-bit encoding
("Line too long"); `List-Unsubscribe` was RFC-2047-encoded (breaks one-click unsubscribe); the app's own VERP return-path was
rejected by the sender-ownership rule; bounce-forwarder permissions drifted to unreadable; a relay probe from loopback proves nothing.

## 6. Limitations and outstanding work (be aware)

1. **Phase 2 not done: the React frontend redesign** (user / company-admin / super-admin dashboards from the three prototypes) and the
   corresponding API wiring, loading/empty/error states, and the onboarding UI for companies/invites. The backend APIs above are ready for it.
2. **Automations still send through Brevo only** (`brevo.services.send_automation_email`). Campaigns and "Send test" use the provider layer
   (test emails use no quota credit and create no `OutboundMessage`; the Brevo test path is unchanged).
3. Brevo webhooks → `OutboundMessage.DELIVERED/BOUNCED` sync is wired, but SMTP has **no delivery confirmation**: "accepted" ≠ delivered.
   Postfix log-based "relay accepted" events are not implemented. Final delivery cannot be proven for SMTP-sent mail.
4. Soft-bounce escalation (N soft bounces → suppress) is not implemented; soft bounces never suppress.
5. Sender-domain verification UI/API (SPF/DKIM/DMARC status per company domain) is not implemented in the backend (removed from the prototype by request).
6. The quota claim serialises on the PlatformSettings row (correct, but one hot lock). Fine at current scale; revisit for very high concurrency.
7. Supabase's pgbouncer in transaction mode works with these short transactions; do not use session-level advisory locks.
8. Not run: the SMTP package on a real internet-facing server (DNS, rDNS, port 25, certbot, ufw, systemd) — see its README "Verified".
9. Deliverability is not guaranteed by any of this: IP/domain reputation, warm-up and consent decide inbox placement.

---

## 7. Revision 2 — dashboards, onboarding, hardening (this session)

### 7.1 Already present before this revision
Backend: tenancy, roles, quotas, providers (Brevo/SMTP), idempotent dispatch, bounce intake, admin APIs, cron scheduler, 261 tests.
Frontend: the regular-user workspace (contacts, lists, tags, segments, signup forms, templates, campaigns, scheduling, analytics, automations).

### 7.2 Newly implemented
**Frontend (React/Vite, all wired to real APIs — no mock data)**
* Role-based redirect after login (`super_admin → /platform`, `company_admin → /company`, else `/dashboard`); role-aware sidebar, mobile drawer, session-expiry message, `RoleRoute` guards (UX only; backend authoritative). The dead "Search…" box in the header was removed.
* **Company admin** `/company/*`: overview (KPIs, quota bars, 7-day chart), members & invitations (invite, edit role/quotas, deactivate/reactivate, pause campaigns, resend invite), quotas & usage, campaign activity (pause/resume), analytics, suppressions, activity log, company & plan.
* **Platform admin** `/platform/*`: overview/capacity, companies (create, detail, edit plan/quotas/allowed providers, suspend/reactivate, invite administrator), users (activate/deactivate, reset/invite links), plans (create/edit/duplicate/archive, over-commit warning), providers & limits (health, SMTP connection test, guarded provider switch), queue & failed jobs (retry, resolve needs-review, pause/resume queue), campaign monitor, analytics, system health, audit log.
* Public pages: `/accept-invite`, `/forgot-password`. User dashboard shows the user's own quota card; Settings shows role/company.
* **React crash fix:** root cause — `common/exceptions.py` wraps DRF validation errors as `{detail: {field: [..]}}`, and 17 call sites rendered `detail` directly. New `src/utils/formatError.js` (`formatApiError`, `fieldErrors`, `toDisplayText`) handles strings, arrays, nested objects, network/401/403/5xx; all 12 pages and the toast layer now use it. Unit-checked with 15 cases including the exact `{detail:{sender_email:[…]}}` shape.
* Added `.eslintrc.cjs` (`npm run lint` previously failed: no config) and fixed the 3 pre-existing lint errors.

**Backend**
* `POST /api/platform/companies/<id>/members/` — platform admin invites a company admin/user (seat limit, duplicate and role checks, audited). Previously only possible via the Django shell.
* `POST /api/company/members/<id>/resend-invite/` (own company, pending users only).
* `POST /api/auth/forgot-password/` — identical answer for known/unknown emails, link emailed only, never returned.
* Invitation/reset **emails** via Brevo transactional API (`tenancy/invites.py`, `SEND_INVITE_EMAILS`). The link is returned in the API response **only if the email could not be sent**.
* **Soft-bounce escalation** (`brevo/webhooks.py: escalate_soft_bounces`): N consecutive soft bounces in a window → suppression `soft_bounce_limit`. Shared by Brevo and SMTP paths. Migration `contacts.0004` (choices only).
* `ALLOW_PUBLIC_REGISTRATION` flag (default True = unchanged behaviour); `SECRET_KEY` guard when `DEBUG=False`; secure cookies/nosniff/referrer policy/HSTS+SSL-redirect switches when `DEBUG=False`; constant-time comparison for cron and Brevo webhook secrets; `render.yaml` SPA rewrite.

* **Brevo health is now a live check.** Previously it only tested that a key string existed, so the providers page could show "OK" with a wrong/revoked key. It now calls Brevo's read-only `GET /account` (no email sent). Verified only with simulated Brevo responses (`tenancy/tests_invites.py::BrevoLiveHealthTests`), not against your real account.

### 7.3 Security findings
* **Removed** a hard-coded "Demo login: admin / Admin@12345" hint from the login page.
* This archive contained **no** `.env` files, keys or `venv/` (checked by file name and by pattern scan). The earlier archive reportedly did: **treat those credentials as compromised and rotate them** — not done by me, I have no access: Brevo API key, Supabase DB password, Django `SECRET_KEY` (rotating it signs everyone out and voids outstanding invite links). There is no Git history in this archive, so history was not inspected: run `git log -p -S"xkeysib" --all` / a tool such as gitleaks on your real repository.
* Open registration creates **unlimited standalone accounts** (pre-existing business rule, not changed). Recommended: `ALLOW_PUBLIC_REGISTRATION=False` for multi-tenant use.
* Cron/webhook secrets may still be passed as `?secret=` (kept for compatibility); prefer the headers — URLs are logged.
* Tokens live in `localStorage` (pre-existing design; XSS would expose them).
* Root-level `original_models.py`, `original_serializers.py`, `original_services.py`, `original_views.py` look like stale reference copies; left untouched — review and delete if unused.

### 7.4 Tests actually run (this session)
| Check | Result |
|---|---|
| `manage.py check` / `makemigrations --check` | no issues / no changes detected |
| Baseline backend suite before changes (SQLite) | **261 run, 261 passed, 6 skipped** (skipped = PostgreSQL-only concurrency tests) |
| Full backend suite after changes (SQLite) | **277 run, 271 passed, 0 failed, 6 skipped** — 16 new tests (invitations, resend, platform onboarding, forgot-password, soft-bounce escalation, registration flag) |
| Re-run after the last edits (secret comparison, SMTP activation validation, tests): `tenancy scheduling brevo accounts providers.tests_bounces` | 110 run: 109 passed; 1 failure was a **test-isolation bug** (shared throttle cache → 429) in my new test, fixed; `accounts` re-run: 12/12 pass. The *entire* suite was not re-run once more after that final fix |
| PostgreSQL | **not run** (no PostgreSQL in the sandbox). The 6 concurrency tests remain unverified in this session (they passed on PostgreSQL 16 in the earlier revision) |
| `manage.py check --deploy` (DEBUG=False, random key) | 2 warnings, both intentional deployment decisions (HSTS, SSL redirect) |
| Frontend `npm run lint` | clean (config added; 3 pre-existing errors fixed) |
| Frontend `npm run build` | succeeds (one chunk-size warning, pre-existing) |
| Error formatter | 15/15 unit checks (node) |
| Live API smoke test (Django dev server on SQLite, 4 personas) | 46 checks; 45 passed + 1 over-broad check of mine that matched the env-var *name* `BREVO_API_KEY` in a health message (no secret value) — effectively 46/46. Covers: every endpoint the new pages call, role enforcement (403/401), tenant isolation by direct id access (404), invite → accept → single-use → login, forgot-password non-enumeration |
| Browser / E2E / responsive testing | **not performed** |
| Secret scan of the package | no key/token patterns found; no `.env`, `venv`, `node_modules`, caches, DB files |

### 7.5 Known limitations / manual steps
* **No browser/UI automation was run.** Frontend verification = lint + production build + formatter unit checks + a live API smoke test of every endpoint the new pages call (response keys, role enforcement, tenant isolation, onboarding). Layout/responsiveness and every button were **not** visually exercised — please click through each page once.
* Real Brevo sending, webhook delivery, invitation email delivery, real SMTP server, DNS, Render and Supabase were **not** available: **not externally verified**.
* PostgreSQL concurrency tests (6) were skipped here (SQLite only): run them against PostgreSQL before production.
* Provider switch UI confirms and the backend validates provider names/readiness at switch time for running campaigns; activation of SMTP at *platform* level relies on the connection test + `validate-smtp.sh` — a passing test is not proof of delivery.
* Not implemented: sender-domain verification UI (backend absent), automations via SMTP (still Brevo-only), SMTP delivery confirmation (impossible by protocol), self-service forgot-password email needs Brevo configured (otherwise nothing is sent), no per-company provider credentials, no payment processing, no E2E browser tests.

---

## 8. Revision 3 — sign-up, login types, join-by-invitation, per-campaign provider

### 8.1 Root cause of "everyone lands on the same dashboard" (found in the previous archive)
1. `LoginPage` always navigated to `/dashboard`; there was no role-based redirect.
2. The frontend had **no** company-admin or platform-admin pages or routes at all (only the backend APIs existed), and the sidebar was one fixed menu for everyone.
3. Sign-up (`/register`) created a standalone account only (no company, no quota), and there was no way for a customer to create a company or join one by invitation from the UI.
(The backend already returned the real role in `/auth/login/` and `/auth/me/`, and enforced permissions; those parts were correct.)

### 8.2 Dashboards: existing vs missing (now)
| Dashboard | Before | Now |
|---|---|---|
| User `/dashboard` | existed | kept; added own-usage card |
| Company Admin `/company` (alias `/company-admin`) | **missing in UI** (API existed) | 8 pages |
| SaaS Super Admin `/platform` (alias `/saas-admin`) | **missing in UI** (API existed) | 11 pages |

### 8.3 What was added
* `POST /api/auth/register-company/` — creates the Company (status *trial*, on the plan named `TRIAL_PLAN_NAME`, default "Trial": 100/day, 1000/month, 3 users, all env-configurable) and its first **Company Admin**. Role/plan/quota/company are fixed server-side; any such fields in the request are ignored. If the trial plan is archived, sign-up is refused (503) rather than creating a company with no limits. `ALLOW_COMPANY_SIGNUP=False` disables it. Audited as `company.registered`.
* `GET /api/auth/invite-info/?token=` and a stricter `POST /api/auth/accept-invite/` (optional `email` must match the invited address; optional names; role/company can never be changed here).
* Pages: `/signup` (Create company | Join), `/join` (paste invitation link or code), `/accept-invite?token=` (from the emailed link), three-tab login. The tab is a hint only; the verified role decides the destination and a message is shown on mismatch. `/register` now redirects to `/signup` (the old standalone sign-up form is no longer reachable from the UI; the API endpoint remains, governed by `ALLOW_PUBLIC_REGISTRATION`).
* **Per-campaign provider choice:** new field `Campaign.requested_provider` (migration `campaigns.0005`, additive), `GET /api/campaigns/providers/` (names + readiness only), a "Send with" selector on campaign create/edit shown only when the user has more than one allowed provider. The choice is validated on save and re-validated when sending starts (manual **and** scheduled share the same claim step), frozen into `Campaign.provider`, and never silently replaced. A bug in my first version (unbound variable when the choice had been revoked) was found by a test and fixed.
* The invitation "code" is the signed token (paste the link or the token). No separate short-code model was created.

### 8.3b Hard-coded credentials removed
`seed_data` used to create a Django superuser with the public password `Admin@12345`, and `docs/RENDER_DEPLOY.md` told you to run it on the **production** shell. It now (a) refuses to run when `DEBUG=False`, (b) uses `SEED_ADMIN_PASSWORD` or a random password shown once, and the docs no longer mention a fixed password. **If you ever ran `seed_data` on a live database, that `admin` account has the old known password: change or delete it now.**

### 8.4 Not done / honest limits
* Trial **expiry** is not implemented (no end-date field): a trial company behaves like an active one on the Trial plan until the Super Admin changes it.
* No email verification of the sign-up address (anyone can create a company with any email). Consider enabling it before opening sign-up publicly.
* Company-level `preferred_provider` is chosen in *Company & plan*; there is no per-user provider default.
* Browser/E2E testing was still not performed.

### 8.5 Tests (this revision)
| Check | Result |
|---|---|
| Full backend suite (SQLite) | **293 run, 287 passed, 0 failed, 6 skipped** (skipped = PostgreSQL-only concurrency tests, not run here) |
| New tests this revision (`tenancy/tests_signup.py`, 15) | company sign-up creates Company + Company Admin on the limited trial plan; request cannot choose role/plan/quota/company/superuser; duplicate company/email, weak password and mismatch rejected with nothing half-created; sign-up can be disabled; archived trial plan blocks sign-up; no self-promotion via `/auth/register/` or `PATCH /auth/me/`; new admin reaches `/company` (200) but not `/platform` (403); invite-info shows company, single-use; join assigns the inviter's company and role even if the request tries to tamper; wrong email refused without consuming the link; login returns the verified role for user / company admin / super admin; provider options follow policy and expose no secrets; disallowed provider refused on save; requested provider is frozen and actually used for sending; revoked or unconfigured choice is refused, never silently switched |
| `makemigrations --check` | no changes detected |
| Frontend lint / build | clean / succeeds |
| Browser / E2E | **not performed** — the sign-up, join and login screens were verified by build + API tests only |
| Scheduled campaigns | share the same claim step as "send now" (`send_campaign_now`), covered by the provider-freeze tests; a cron-driven end-to-end run was not repeated this revision |
