#!/usr/bin/env bash
# STAGE 1 of 3: install and configure the SMTP server. Outbound internet delivery stays HELD.
#   Stage 1  setup-smtp.sh          (this script)   install packages, TLS cert, Postfix, OpenDKIM, bounce intake
#   Stage 2  validate-smtp.sh dns   publish DNS records, then verify them
#   Stage 3  activate-production.sh enable real outbound delivery (explicit confirmation required)
# Usage: sudo ./setup-smtp.sh [--skip-certbot] [--dry-run] [--yes]
MF_SCRIPT="setup-smtp"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
SKIP_CERTBOT=0
for a in "$@"; do case "$a" in
  --skip-certbot) SKIP_CERTBOT=1 ;; --dry-run) DRY_RUN=1 ;; --yes) ASSUME_YES=1 ;;
  -h|--help) sed -n '2,9p' "$0"; exit 0 ;; *) die "Unknown option: $a" ;; esac; done

require_root; check_os; load_env; validate_common_env
export TLS_CERT_MODE="${TLS_CERT_MODE:-letsencrypt}"
[ "${TLS_CERT_MODE}" = "letsencrypt" ] && require_vars LETSENCRYPT_EMAIL

log "Target host: ${SMTP_HOSTNAME} (${SMTP_PUBLIC_IP}); sending domain ${SENDING_DOMAIN}; bounce domain ${BOUNCE_DOMAIN}"
warn "Before going live you MUST confirm your hosting provider permits outbound port 25 and bulk/marketing email (see README step 0)."
confirm "Install and configure Postfix + OpenDKIM on THIS machine?" || die "Cancelled."

# ---- 1. packages ----------------------------------------------------------------------------------
log "installing packages"
echo "postfix postfix/main_mailer_type select Internet Site" | run debconf-set-selections
echo "postfix postfix/mailname string ${SMTP_HOSTNAME}"      | run debconf-set-selections
run apt-get update -qq
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postfix opendkim opendkim-tools libsasl2-modules \
    sasl2-bin ca-certificates openssl dnsutils swaks ufw python3 logrotate
[ "${TLS_CERT_MODE}" = "letsencrypt" ] && run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot

# ---- 2. service account + bounce forwarder ----------------------------------------------------------
id mailflow >/dev/null 2>&1 || run useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin mailflow
run mkdir -p "${MF_ETC}/secrets" /var/lib/mailflow-smtp /var/log/mailflow-smtp
run install -m 755 -o root -g root "${SCRIPT_DIR}/bounce-forwarder.py" /usr/local/sbin/mailflow-bounce-forwarder
secret_file_ensure "${BOUNCE_WEBHOOK_SECRET_FILE:-${MF_ETC}/secrets/bounce-webhook-secret}" 32
if [ "${DRY_RUN}" != "1" ]; then
  sf="${BOUNCE_WEBHOOK_SECRET_FILE:-${MF_ETC}/secrets/bounce-webhook-secret}"
  # The forwarder runs as `mailflow`, so ONLY that user (and root) can read the secret.
  chown root:mailflow "${sf}"; chmod 640 "${sf}"; fix_etc_perms
  { echo "# Managed by MailFlow setup-smtp.sh"; echo "BOUNCE_WEBHOOK_URL=${BOUNCE_WEBHOOK_URL:-}"
    echo "BOUNCE_WEBHOOK_SECRET_FILE=${sf}"; } > "${MF_ETC}/bounce.conf"
  chown root:mailflow "${MF_ETC}/bounce.conf"; chmod 640 "${MF_ETC}/bounce.conf"
  chown mailflow:mailflow /var/lib/mailflow-smtp /var/log/mailflow-smtp
fi

# ---- 3. TLS certificate ------------------------------------------------------------------------------
if [ "${TLS_CERT_MODE}" = "letsencrypt" ] && [ "${SKIP_CERTBOT}" = "0" ]; then
  if [ -r "/etc/letsencrypt/live/${SMTP_HOSTNAME}/fullchain.pem" ]; then log "certificate for ${SMTP_HOSTNAME} already present (kept)"
  else
    resolved="$(dig +short A "${SMTP_HOSTNAME}" 2>/dev/null | tail -1 || true)"
    [ "${resolved}" = "${SMTP_PUBLIC_IP}" ] || die "${SMTP_HOSTNAME} resolves to '${resolved:-nothing}', not ${SMTP_PUBLIC_IP}. Create the A record first (Let's Encrypt must reach this server on port 80)."
    run certbot certonly --standalone --non-interactive --agree-tos -m "${LETSENCRYPT_EMAIL}" -d "${SMTP_HOSTNAME}"
  fi
  if [ "${DRY_RUN}" != "1" ]; then
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/mailflow-postfix.sh <<'HOOK'
#!/bin/sh
# Reload Postfix after every certificate renewal so it serves the new certificate.
systemctl reload postfix
HOOK
    chmod 755 /etc/letsencrypt/renewal-hooks/deploy/mailflow-postfix.sh
  fi
fi

# ---- 4. OpenDKIM then Postfix (each validates before reloading) ------------------------------------------
dry=(); [ "${DRY_RUN}" = "1" ] && dry=(--dry-run)
"${SCRIPT_DIR}/configure-opendkim.sh" "${dry[@]}"
"${SCRIPT_DIR}/configure-postfix.sh" "${dry[@]}"

# ---- 5. monitoring + log rotation ------------------------------------------------------------------------------
if [ "${DRY_RUN}" != "1" ]; then
  install -m 644 "${SCRIPT_DIR}/logrotate/mailflow-smtp" /etc/logrotate.d/mailflow-smtp
  install -m 755 "${SCRIPT_DIR}/health-check.sh" /usr/local/sbin/mailflow-health-check
  install -m 644 "${SCRIPT_DIR}/lib.sh" /usr/local/lib/mailflow-smtp-lib.sh 2>/dev/null || true
  install -m 644 "${SCRIPT_DIR}/systemd/mailflow-smtp-health.service" /etc/systemd/system/
  install -m 644 "${SCRIPT_DIR}/systemd/mailflow-smtp-health.timer"   /etc/systemd/system/
  cp "${ENV_FILE}" "${MF_ETC}/requirements.env"; chmod 600 "${MF_ETC}/requirements.env"
  systemctl daemon-reload; systemctl enable --now mailflow-smtp-health.timer >/dev/null 2>&1 || warn "could not enable the health timer"
fi
state_set installed yes

ok "STAGE 1 COMPLETE. Outbound internet delivery is HELD (nothing leaves this server yet)."
cat <<NEXT

Next steps (in order):
  1. Publish DNS records:  see dns-records.example.txt and /root/mailflow-dns/*.dkim.txt
  2. Verify them:          sudo ./validate-smtp.sh dns
  3. Lock down the host:   sudo ./firewall-setup.sh        (review --dry-run first)
  4. Run all checks:       sudo ./validate-smtp.sh all
  5. Go live (explicit):   sudo ./activate-production.sh
The application password is in ${SMTP_AUTH_PASSWORD_FILE} (root only). It was NOT printed.
NEXT
