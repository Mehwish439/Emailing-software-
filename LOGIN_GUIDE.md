# Login & Dashboard Guide

Plain-language guide: who you are → how to get an account → where you sign in → which dashboard opens.
Technical setup is in [`SETUP_GUIDE.md`](SETUP_GUIDE.md). What changed is in [`docs/UPGRADE_NOTES.md`](docs/UPGRADE_NOTES.md).

## The three kinds of account

| Account | Who it is | How it is created | Dashboard (URL) |
|---|---|---|---|
| **SaaS Super Admin** | You, the platform owner (and people you trust) | **Never from the website.** One command on the server (below) | **/platform** (alias `/saas-admin`) |
| **Company Admin** | The person who runs one company | Signs up with **Create a new company**, *or* is invited by the Super Admin | **/company** (alias `/company-admin`) |
| **Company User** | An employee of a company | **Invited** by their Company Admin, then **Join an existing company** | **/dashboard** |

You never choose your own role. The server decides it when the account is created, and every page and API call re-checks it.

---

## 1. Create the first SaaS Super Admin (one time, on the server)

There is deliberately no sign-up page for this role, and no default password.

1. Create a normal account (either way works):
   * `python manage.py createsuperuser` (asks you for a username, email and password), **or**
   * sign up on the website with *Create a new company* using your own email.
2. Promote it (replace the email with yours):

```bash
cd backend
python manage.py shell -c "from django.contrib.auth import get_user_model as g; u=g().objects.get(email='you@example.com'); u.role='super_admin'; u.save()"
```

3. Sign in (section 4). You land on the **SaaS Super Admin dashboard**.

> If you promoted a "Create a new company" account, it also still belongs to that trial company. That is harmless, but for a clean owner account use `createsuperuser`.

---

## 2. Sign up

Open **/signup**. There are two tabs.

### A. Create a new company  (you become the Company Admin)
1. Company name, your name, work email, password + confirmation → **Create company**.
2. The system creates the company on a **limited Trial plan** (default 100 emails/day, 1,000/month, 3 users — the Super Admin can change this under *Plans & quotas*) and your Company Admin account.
3. You are signed in and sent straight to the **Company Admin dashboard**.

### B. Join an existing company  (you become a regular user)
1. Ask your Company Admin to invite you (*Company dashboard → Members & invitations → Invite user*).
2. You receive an **invitation link** by email. If email is not configured, your admin copies the link from the screen and sends it to you.
3. Open the link (or go to **/join** and paste the link or code). The page shows which company you are joining.
4. Enter your name, **the same work email the invitation was sent to**, and a password → **Join company**.
5. Go to **/login** and sign in. You land on the **User dashboard**.

An invitation link works **once** and expires after **7 days**. Ask for a new one if it fails.

---

## 3. Super Admin creates a company for a customer (alternative to self sign-up)

1. Sign in as Super Admin → **Companies → New company** → pick a plan.
2. Open the company → **Invite administrator / user** → role *Company admin*.
3. Send the link to the customer. They open it, enter their details and password (section 2B, step 3–5), then sign in. They land on the **Company Admin dashboard**.

---

## 4. Sign in

Open **/login**. Pick the tab that describes you, then enter your email (or username) and password.

| Tab | Use it if you are… |
|---|---|
| Company Admin | the administrator of a company |
| Company User (default) | an employee |
| SaaS Super Admin | the platform owner |

**The tab does not give you any power.** The server checks your real role. If you pick the wrong tab you are still signed in, told what kind of account you have, and taken to *your* correct dashboard.

Forgot your password → **Forgot your password?** on the login page (works only when email sending is configured; otherwise ask your admin for a new link).

---

## 5. Which dashboard opens, and what is in it

| After signing in as… | You land on | What you can do there |
|---|---|---|
| Company User | **/dashboard** | Campaigns, contacts, lists, tags, segments, templates, signup forms, scheduling, automations, analytics, your own usage limits, settings |
| Company Admin | **/company** | Overview, **Members & invitations** (invite, roles, quotas, deactivate, resend), **Quotas & usage**, **Campaign activity**, Analytics, Suppressions, Activity log, **Company & plan** (name, allowed provider choice, plan info). Link to *My campaigns* in the top bar |
| Super Admin | **/platform** | Overview, **Companies**, Users, **Plans & quotas**, **Providers & limits** (Brevo / SMTP, rate limits), **Queue & failures**, Campaign monitor, Analytics, **System health**, Audit log. Link to *My campaigns* in the top bar |

Typing an address you are not allowed to use (for example a user opening `/company`) shows **Access denied**, and the server also refuses the underlying API calls (403/404).

---

## 6. Choosing Brevo or our own SMTP for a campaign

* **Super Admin → Providers & limits:** pick the platform default. Tick **"Let companies choose among their approved providers"** to allow choice. SMTP can only be activated once it is configured on the server.
* **Super Admin → Companies → (company) → Edit plan & quotas:** tick which providers that company may use (Brevo, SMTP).
* **Company Admin → Company & plan:** pick the company's preferred provider.
* **Anyone creating a campaign:** a **"Send with"** menu appears on the campaign form only when you have more than one allowed provider. Otherwise the form just tells you which provider will be used.
* The provider is **locked in when sending starts**, also for scheduled campaigns, and is never changed automatically. If the chosen provider is no longer allowed or not configured, the send is refused with a clear message — it does not quietly use the other one.

---

## 7. Quick fixes

| Problem | What to do |
|---|---|
| "Invalid, expired or already used" on a link | Ask your admin to **Resend invite** |
| "Issued for a different email address" | Use the exact email the invitation was sent to |
| "A company with this name already exists" | Pick another name, or ask that company's admin to invite you |
| You open the wrong dashboard | Use the top-bar links (*Company admin*, *Platform admin*, *My campaigns*) if you have more than one role |
| No sign-up button for Super Admin | By design — see section 1 |
| Want invitation-only sign-up | Set `ALLOW_COMPANY_SIGNUP=False` (and `ALLOW_PUBLIC_REGISTRATION=False`) on the backend |
