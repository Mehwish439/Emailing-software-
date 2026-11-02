# Troubleshooting

Start with: `sudo ./validate-smtp.sh all` and `sudo ./health-check.sh`. Logs: `/var/log/mail.log`, `journalctl -u postfix -u opendkim`.

## Installation

| Symptom | Cause / fix |
|---|---|
| `Set these in requirements.env (empty or still CHANGE_ME)` | The script refuses to guess. Fill the listed variables. |
| `<host> resolves to '…', not <ip>` (certbot step) | Create the **A record** first and wait for propagation; Let's Encrypt must reach port 80 on this server. |
| `TLS certificate/key not found` | Run `setup-smtp.sh` (obtains it) or use `TLS_CERT_MODE=existing` with `TLS_CERT_FILE/TLS_KEY_FILE`. |
| `Postfix validation failed; previous configuration restored` | Read the lines printed above it (`postfix check` output). Fix `requirements.env`/templates and re-run; nothing was reloaded. |
| `Safety check failed (open-relay risk)` | `mynetworks` contained a non-loopback network. Never add application IPs to `mynetworks`; they authenticate with SASL. |

## Application cannot send (Django side)

| Error in MailFlow | Meaning / fix |
|---|---|
| `Email provider 'smtp' is not ready: SMTP_HOST is not configured` | Set the `SMTP_*` variables on the Django host and restart it. |
| `SMTP_USE_TLS … and SMTP_USE_SSL … are mutually exclusive` | Enable exactly one: STARTTLS (587) **or** implicit TLS (465). |
| `SMTP authentication failed (535)` | Wrong `SMTP_USERNAME/PASSWORD`. Password is in `/etc/mailflow-smtp/secrets/smtp-auth-password`; re-run `configure-postfix.sh` to re-apply it. |
| `SMTP 553 … Sender address rejected: not owned by user` | The From domain isn't one of `SENDING_DOMAIN`/`EXTRA_SENDING_DOMAINS` (`add-sending-domain.sh`), or `SMTP_BOUNCE_DOMAIN` ≠ `BOUNCE_DOMAIN`. |
| `Could not connect to SMTP server` | Firewall: your Django egress IP must be in `APP_SERVER_IPS`; port 587 reachable? `swaks --server <host> --port 587 --tls --quit-after EHLO`. |
| Campaign stays *processing*, messages *deferred* | Provider unreachable — **no failover happens silently**. Fix the server, or use the audited switch-provider action. |
| Message state **needs review** | The connection dropped after the body was sent: it may or may not have been delivered. It is never auto-retried. Check `grep <message-id> /var/log/mail.log`, then *resolve* it (sent / retry) in the admin queue. |

## Delivery

| Symptom in `mail.log` | Meaning |
|---|---|
| `Connection timed out … :25` | Outbound port 25 blocked by your host. Ask the provider; use their relay if they offer one. |
| `status=deferred (host … said: 421/450/451 …)` | Temporary (greylisting, rate limit). Postfix retries with backoff. Lower `DEST_RATE_DELAY`/`DEST_CONCURRENCY`, add `PER_DOMAIN_RATE_DELAY`. |
| `said: 550 5.7.1 … blocked / listed / reputation` | IP/domain reputation. Stop, check blocklists (e.g. Spamhaus lookup), fix SPF/DKIM/DMARC/PTR, warm up more slowly. |
| `said: 550 5.1.1 user unknown` | Hard bounce: MailFlow suppresses the address automatically (needs the bounce path working). |
| `milter-reject / tempfail` | OpenDKIM is down: `systemctl status opendkim`. Mail is *deferred*, never sent unsigned (`milter_default_action=tempfail`). |
| `SASL authentication failed` | Bad credentials; repeated failures from unknown IPs = attack → keep port 587 firewalled to `APP_SERVER_IPS`, consider fail2ban. |

Mail queue: `postqueue -p` · `postqueue -f` · `postcat -q <ID>` · `postsuper -d <ID>` · `postsuper -d ALL deferred` (destructive).

## Bounces are not reaching the application

1. `dig MX <BOUNCE_DOMAIN>` must point at the SMTP host.
2. `swaks --server <this host's IP> --port 25 --to bounce+1.2.abcdef012345@<BOUNCE_DOMAIN> --quit-after RCPT` must be accepted.
3. `grep 'mailflow-bounce' /var/log/mail.log` — `status=sent` is good; `Command output: …` explains failures:
   `Permission denied …bounce.conf` → `sudo bash -c '. ./lib.sh; ENV_FILE=./requirements.env; fix_etc_perms'`; `non-HTTPS URL` → use an `https://` `BOUNCE_WEBHOOK_URL`;
   `application rejected (HTTP 401)` → the secret differs from Django's `SMTP_BOUNCE_WEBHOOK_SECRET`.
4. Messages queued for the pipe are retried automatically (`postqueue -f` to retry now).

## DKIM / SPF / DMARC

* `opendkim-testkey -d <domain> -s <selector> -k /etc/opendkim/keys/<domain>/<selector>.private -vvv`
* DNS TXT values with 2048-bit keys must be split into ≤255-char strings — copy from `/root/mailflow-dns/<domain>.dkim.txt` exactly.
* `dkim=fail` at Gmail: DNS key ≠ server key (re-publish), or a relay modified the body. Check `Authentication-Results` in a received message.
* DMARC alignment: the visible **From** domain must equal (or be a subdomain of) the SPF-checked and DKIM-signing domain.

## Disk, queue, recovery

* Disk full → Postfix stops accepting mail. `du -xh /var/spool/postfix | sort -h | tail`; `journalctl --vacuum-size=200M`; fix, then `postqueue -f`.
* Rotate sooner at high volume: edit `/etc/logrotate.d/rsyslog` (mail.log) to `daily`/`rotate 7`.
* After a crash: `systemctl restart postfix opendkim`; the queue is on disk and survives.
