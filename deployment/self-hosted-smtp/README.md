# MailFlow self-hosted SMTP (Postfix + OpenDKIM) — Ubuntu 24.04 LTS

> See also: [`SETUP_GUIDE.md`](../../SETUP_GUIDE.md) (§10.8 application side, §10.11 troubleshooting) and [`docs/UPGRADE_NOTES.md`](../../docs/UPGRADE_NOTES.md).

A tested setup package for the **outbound SMTP server** that MailFlow can use instead of (or alongside) Brevo.
It runs on its **own server**, separate from the Django API / React frontend.

```
Django API (Render etc.) ──587 STARTTLS + AUTH──▶ Postfix ──▶ OpenDKIM signs ──▶ recipients' mail servers
        ▲                                            │
        └── HTTPS webhook ◀── mailflow-bounce-forwarder ◀── bounces/complaints to bounce+…@bounce domain (port 25)
```

> **Honest status.** These scripts were executed end-to-end on a real Ubuntu host with real Postfix, OpenDKIM and
> SASL: install, idempotent re-run, relay-safety probes, DKIM signing (signature verified cryptographically),
> authenticated TLS submission, delivery, and the full bounce path into the application (see *Verified* at the end).
> They have **not** been run on *your* server, against your DNS, or sent to real inboxes. Nothing here guarantees
> inbox placement or delivery.

## Step 0 — Before you touch a server (do not skip)

1. **Hosting permission.** Many providers block outbound **port 25** by default and many prohibit marketing/bulk mail.
   Get written confirmation that your plan allows (a) outbound port 25 and (b) the volume and type of email you intend.
   `validate-smtp.sh` tests port 25 reachability, but it cannot tell you the provider's *policy*.
2. **A clean IP.** New IPs have no reputation. Warm up slowly (start with tens/day, double gradually).
3. **Consent.** Only email recipients who opted in. MailFlow suppresses unsubscribes, hard bounces and complaints
   automatically; this server never re-enables them.
4. **Rate limits come from your provider's written policy**, not from the examples in `requirements.env.example`.

## Three separate stages (installation ≠ DNS ≠ production)

| Stage | Command | What it does | Mail leaves the server? |
|---|---|---|---|
| 1 Install | `sudo ./setup-smtp.sh` | Packages, TLS cert, Postfix, OpenDKIM, bounce intake | **No** — outbound delivery is *held* (`defer_transports`) |
| 2 Verify | `sudo ./validate-smtp.sh dns` (+ `all`) | Checks A/PTR/SPF/DKIM/DMARC/MX, TLS, relay safety | No |
| 3 Activate | `sudo ./activate-production.sh` | Refuses unless checks pass **and** you type a confirmation | **Yes** |

Emergency brake at any time: `sudo ./activate-production.sh --deactivate` (queued mail is kept, nothing is lost).

## Install

```bash
# On the SMTP server (fresh Ubuntu 24.04), as root:
git clone <your repo> && cd <repo>/deployment/self-hosted-smtp
cp requirements.env.example requirements.env && chmod 600 requirements.env
nano requirements.env            # replace every CHANGE_ME

# Create DNS first: the A record for SMTP_HOSTNAME (needed for the Let's Encrypt certificate).
sudo ./setup-smtp.sh --dry-run   # preview; changes nothing
sudo ./setup-smtp.sh             # stage 1
```

What `setup-smtp.sh` does (and promises): checks OS/root/variables; backs up every config it touches to
`/var/backups/mailflow-smtp/<timestamp>/`; renders templates; **validates before reloading** and restores the backup
if validation fails; never prints secrets; is safe to re-run (existing DKIM keys and passwords are never overwritten).

Then:

```bash
cat /root/mailflow-dns/*.dkim.txt        # publish these + the rest of dns-records.example.txt
sudo ./validate-smtp.sh dns              # stage 2 -- repeat until green
sudo ./firewall-setup.sh --dry-run       # review, then run without --dry-run
sudo ./validate-smtp.sh all
sudo ./activate-production.sh            # stage 3
```

## Connecting the application

On the Django host set (never commit these; the password is in `/etc/mailflow-smtp/secrets/smtp-auth-password`):

```
EMAIL_PROVIDER=smtp                     # fallback only; the platform admin selects the active provider in the UI/API
SMTP_HOST=mail.send.example.com
SMTP_PORT=587
SMTP_USERNAME=mailflow-app
SMTP_PASSWORD=<contents of the secret file>
SMTP_USE_TLS=True                       # STARTTLS on 587.  Use SMTP_USE_SSL=True ONLY with port 465 -- never both
SMTP_USE_SSL=False
SMTP_FROM_EMAIL=news@send.example.com
SMTP_BOUNCE_DOMAIN=bounce.example.com
SMTP_BOUNCE_WEBHOOK_SECRET=<contents of /etc/mailflow-smtp/secrets/bounce-webhook-secret>
SMTP_RATE_LIMIT=25                      # software cap; keep <= your provider's written limit
```

Put your Django host's **public egress IPs** in `APP_SERVER_IPS` (they are the only addresses allowed on port 587).
Platforms with shared/changing outbound IPs (check your host's documentation for fixed/static outbound IPs) cannot be
IP-restricted reliably; if you must allow wider access, keep SASL + TLS and add fail2ban rate limiting.

Then, as a platform admin: `PATCH /api/platform/settings/ {"active_provider": "smtp"}` (or the Super Admin UI).
Check `GET /api/platform/health/?probe=smtp` — it connects and authenticates but **never sends mail**.
Brevo keeps working untouched; a campaign's provider is frozen when it starts sending.

## Operations

| Task | Command |
|---|---|
| Health (Nagios-style exit code) | `./health-check.sh` · `./health-check.sh --json` (a timer writes `/var/lib/mailflow-smtp/health.json` every 5 min) |
| Queue | `postqueue -p` · `postqueue -f` (retry now) · `postcat -q <id>` · `postsuper -d <id>` (delete one) |
| Why is mail deferred? | `grep -E 'status=(deferred|bounced)' /var/log/mail.log \| tail` · see `troubleshooting.md` |
| Add another sending domain | `sudo ./add-sending-domain.sh example.org` then publish its DNS |
| Backup config (no secrets) | `sudo ./backup-config.sh` (`--include-secrets` → store encrypted, off-server) |
| Certificate renewal | automatic (certbot timer); a deploy hook reloads Postfix; `ufw` opens port 80 only during renewal |
| Logs | `/var/log/mail.log` (rotated by rsyslog's logrotate) · `journalctl -u postfix -u opendkim` |

**Per-domain pacing:** `PER_DOMAIN_RATE_DELAY=gmail.com=2s,yahoo.com=3s` creates dedicated Postfix transports with
concurrency 1. **Global cap:** `GLOBAL_RATE_PER_MINUTE` is Postfix's per-client message rate (the application is the
client). The application *also* enforces its own platform rate limit and per-company fair queueing.

## Recovery / rollback

* A script failed mid-way → it already restored the previous config (look for “restored”). Postfix keeps running on the old config.
* Restore manually: `sudo cp -a /var/backups/mailflow-smtp/<ts>/etc/postfix/* /etc/postfix/ && sudo postfix reload`.
* Stop all outbound immediately: `sudo ./activate-production.sh --deactivate`.
* Service restart: `sudo systemctl restart postfix opendkim`. Queue survives restarts (`/var/spool/postfix`).
* Roll back the application side: set `EMAIL_PROVIDER=brevo` / `PATCH active_provider=brevo`. In-flight campaigns keep their
  frozen provider; use the audited *switch-provider* action (blocked while any message has an unknown outcome).

## Files

`setup-smtp.sh` · `configure-postfix.sh` · `configure-opendkim.sh` · `validate-smtp.sh` · `health-check.sh` ·
`firewall-setup.sh` · `activate-production.sh` · `add-sending-domain.sh` · `backup-config.sh` · `bounce-forwarder.py` ·
`lib.sh` · `postfix/{main,master}.cf.template` · `opendkim/*.template` · `systemd/` · `logrotate/` ·
`dns-records.example.txt` · `requirements.env.example` · `troubleshooting.md` · `security-checklist.md`

## Verified (what was actually run)

On Ubuntu 24.04, Postfix 3.8.6, OpenDKIM, Cyrus SASL, swaks, shellcheck:
`shellcheck` clean · dry-run changes nothing · idempotent re-run · `postfix check` clean · relay probes **from a non-loopback
address** (open relay rejected on 25 and 587, bad password rejected, foreign sender domain rejected, bounce domain rejects
non-bounce recipients, VERP accepted) · TLS 1.3 + AUTH only after STARTTLS · authenticated submission from the Django provider ·
**DKIM signature verified with `dkimpy` against the published TXT record** · delivery to a stand-in recipient server ·
recipient 550 → Postfix bounce → VERP → pipe → HTTPS forwarder → Django → recipient `bounced` + `hard_bounce` suppression ·
activation refused while DNS checks failed · emergency brake · health check · firewall dry-run.

**Not verifiable here:** real DNS/rDNS, outbound port 25 to the internet, certbot issuance, ufw enforcement (no kernel
firewall in the test host), systemd timers (no systemd in the test host — a shim was used), inbox placement, and your
provider's policies.
