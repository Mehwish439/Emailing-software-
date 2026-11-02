# Production security checklist

Tick every item before `activate-production.sh`. `validate-smtp.sh all` automates the ones marked ⚙.

## Relay and authentication
- [ ] ⚙ Not an open relay — probed from a **non-loopback** address (loopback is trusted by design, so probing from 127.0.0.1 proves nothing).
- [ ] ⚙ `mynetworks` is loopback only; application servers authenticate with SASL.
- [ ] ⚙ AUTH is offered only after STARTTLS; TLS ≥ 1.2.
- [ ] ⚙ An authenticated user can send only as the domains the server DKIM-signs (+ the signed VERP return-path).
- [ ] ⚙ SASL is enabled only on the submission service (587), never on port 25.
- [ ] Port 587 reachable only from `APP_SERVER_IPS` (`firewall-setup.sh`), SSH restricted to your admin IP (`SSH_ALLOW_FROM`), key-based SSH, root login & password SSH disabled.
- [ ] Consider fail2ban for `postfix` / `sshd` jails.

## Secrets
- [ ] No secret in git: `requirements.env` is `chmod 600` and git-ignored; `git log -p | grep -i password` is empty.
- [ ] ⚙ SMTP password file mode 600 (root only); bounce secret 640 `root:mailflow`; DKIM private keys 600 `opendkim`.
- [ ] Application secrets (`SMTP_PASSWORD`, `SMTP_BOUNCE_WEBHOOK_SECRET`, `BREVO_API_KEY`) only in the hosting platform's secret store; none in the frontend bundle.
- [ ] Rotate the SMTP password: delete the secret file, re-run `configure-postfix.sh`, update Django. Rotate DKIM: new selector in `requirements.env`, publish, switch, remove old after 7 days.
- [ ] Back up `/etc/mailflow-smtp` and DKIM keys **encrypted, off-server** (`backup-config.sh --include-secrets`).

## Exposure
- [ ] ⚙ No PostgreSQL / Redis / Postfix control ports reachable from the internet (Redis bound to localhost or private network with a password).
- [ ] ⚙ OpenDKIM milter on `127.0.0.1` only.
- [ ] Unattended security upgrades enabled (`unattended-upgrades`); reboot policy defined.
- [ ] Only ports 22 (restricted), 25, 587 (restricted) and temporarily 80 (renewals) are open.

## Mail hygiene and compliance
- [ ] ⚙ SPF, DKIM, DMARC published and aligned; PTR matches the hostname; ⚙ `milter_default_action=tempfail`.
- [ ] Hosting provider confirmed **in writing**: outbound port 25 allowed, marketing/bulk mail allowed, volume limits noted; rates in `requirements.env` ≤ those limits.
- [ ] Bounce path verified end-to-end; Postmaster/FBL registrations done (Gmail Postmaster Tools, Microsoft SNDS/JMRP, Yahoo FBL).
- [ ] Application suppression active: unsubscribes, hard bounces and complaints are never re-enabled by normal workflows.
- [ ] Warm-up plan and a **small controlled test list** (your own addresses) before any real campaign — never an unapproved live list.

## Monitoring and recovery
- [ ] `mailflow-smtp-health.timer` enabled; alerting on `health.json` status ≠ OK or `GET /api/platform/health/`.
- [ ] Disk, queue-size and certificate-expiry thresholds set in `requirements.env`.
- [ ] You have rehearsed `activate-production.sh --deactivate` and a config restore from `/var/backups/mailflow-smtp/`.
