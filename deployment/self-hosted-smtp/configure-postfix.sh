#!/usr/bin/env bash
# Render and apply the Postfix configuration. Idempotent and safe:
#   * backs up every file it touches   * validates BEFORE reload   * restores backups if validation fails
#   * never prints secrets             * keeps outbound mail HELD until activate-production.sh
# Usage: sudo ./configure-postfix.sh [--dry-run]
MF_SCRIPT="configure-postfix"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

require_root; check_os; load_env; validate_common_env
export GLOBAL_RATE_PER_MINUTE="${GLOBAL_RATE_PER_MINUTE:-0}" DEST_CONCURRENCY="${DEST_CONCURRENCY:-2}" \
       DEST_RATE_DELAY="${DEST_RATE_DELAY:-1s}" MAX_QUEUE_LIFETIME="${MAX_QUEUE_LIFETIME:-2d}" \
       MESSAGE_SIZE_LIMIT="${MESSAGE_SIZE_LIMIT:-26214400}" INET_PROTOCOLS="${INET_PROTOCOLS:-ipv4}"
[[ "${MESSAGE_SIZE_LIMIT}" =~ ^[0-9]+$ ]] || die "MESSAGE_SIZE_LIMIT must be a number of bytes."
[[ "${MAX_QUEUE_LIFETIME}" =~ ^[0-9]+[smhdw]$ ]] || die "MAX_QUEUE_LIFETIME must look like 2d or 12h."
[[ "${INET_PROTOCOLS}" =~ ^(ipv4|ipv6|all)$ ]] || die "INET_PROTOCOLS must be ipv4, ipv6 or all."

command -v postfix >/dev/null || die "Postfix is not installed. Run ./setup-smtp.sh first."
command -v saslpasswd2 >/dev/null || die "sasl2-bin is not installed. Run ./setup-smtp.sh first."

# ---- TLS files --------------------------------------------------------------------------------
case "${TLS_CERT_MODE:-letsencrypt}" in
  letsencrypt) TLS_CERT_FILE_RESOLVED="/etc/letsencrypt/live/${SMTP_HOSTNAME}/fullchain.pem"
               TLS_KEY_FILE_RESOLVED="/etc/letsencrypt/live/${SMTP_HOSTNAME}/privkey.pem" ;;
  existing)    require_vars TLS_CERT_FILE TLS_KEY_FILE
               TLS_CERT_FILE_RESOLVED="${TLS_CERT_FILE}"; TLS_KEY_FILE_RESOLVED="${TLS_KEY_FILE}" ;;
  *) die "TLS_CERT_MODE must be letsencrypt or existing." ;;
esac
if [ "${DRY_RUN}" != "1" ]; then
  [ -r "${TLS_CERT_FILE_RESOLVED}" ] && [ -r "${TLS_KEY_FILE_RESOLVED}" ] || \
    die "TLS certificate/key not found (${TLS_CERT_FILE_RESOLVED}). Run ./setup-smtp.sh (obtains it) or provide TLS_CERT_FILE/TLS_KEY_FILE."
fi
export TLS_CERT_FILE_RESOLVED TLS_KEY_FILE_RESOLVED

# ---- per-domain pacing: each distinct delay -> its own transport (concurrency 1) -----------------
rate_params=""; rate_transports=""; defer_list="smtp"; declare -A seen_delay=()
transport_lines=""
if [ -n "${PER_DOMAIN_RATE_DELAY:-}" ]; then
  IFS=',' read -ra pairs <<< "${PER_DOMAIN_RATE_DELAY}"
  for pair in "${pairs[@]}"; do
    pair="${pair// /}"; [ -n "${pair}" ] || continue
    dom="${pair%%=*}"; delay="${pair#*=}"
    valid_hostname "${dom}" || die "PER_DOMAIN_RATE_DELAY: invalid domain '${dom}'"
    [[ "${delay}" =~ ^[0-9]+[smh]?$ ]] || die "PER_DOMAIN_RATE_DELAY: invalid delay '${delay}' for ${dom}"
    name="rate${delay//[^0-9a-z]/}"
    if [ -z "${seen_delay[${name}]:-}" ]; then
      seen_delay[${name}]=1; defer_list+=" ${name}"
      rate_params+="${name}_destination_rate_delay = ${delay}"$'\n'"${name}_destination_concurrency_limit = 1"$'\n'
      rate_transports+="${name} unix - - n - - smtp"$'\n'
    fi
    transport_lines+="${dom} ${name}:"$'\n'
  done
fi
export RATE_PARAMS="${rate_params%$'\n'}" RATE_TRANSPORTS="${rate_transports%$'\n'}"

# ---- production safety switch ---------------------------------------------------------------------
if [ "$(state_get activated)" = "yes" ]; then export DEFER_LINE="# (production activated: outbound delivery enabled)"
else export DEFER_LINE="defer_transports = ${defer_list}"; fi

init_backup
for f in /etc/postfix/main.cf /etc/postfix/master.cf /etc/postfix/transport /etc/postfix/bounce_recipients.regexp \
         /etc/postfix/sender_login.regexp /etc/postfix/sasl/smtpd.conf /etc/aliases; do backup_file "${f}"; done

run mkdir -p /etc/postfix/sasl
render_template "${SCRIPT_DIR}/postfix/main.cf.template" /etc/postfix/main.cf

# ---- master.cf: replace only our marked block ---------------------------------------------------------
tmp_block="$(mktemp)"; trap 'rm -f "${tmp_block}"' EXIT
render_template "${SCRIPT_DIR}/postfix/master.cf.template" "${tmp_block}"
if [ "${DRY_RUN}" != "1" ]; then
  [ -f /etc/postfix/master.cf ] || die "/etc/postfix/master.cf missing; reinstall postfix."
  sed -i '/^# BEGIN MAILFLOW$/,/^# END MAILFLOW$/d' /etc/postfix/master.cf
  # Ubuntu's stock file already defines `submission` (commented); ours is the only active one.
  sed -i -E 's/^(submission[[:space:]]+inet.*)$/#\1  # disabled by MailFlow (see MAILFLOW block below)/' /etc/postfix/master.cf
  sed -n '/^# BEGIN MAILFLOW$/,/^# END MAILFLOW$/p' "${tmp_block}" >> /etc/postfix/master.cf
fi

# ---- maps -------------------------------------------------------------------------------------------------
esc_bounce="${BOUNCE_DOMAIN//./\\.}"
if [ "${DRY_RUN}" != "1" ]; then
  { echo "# Managed by MailFlow. Accept ONLY signed-VERP-shaped bounce addresses."
    echo "/^bounce\\+[0-9]+\\.[0-9]+\\.[0-9a-f]{12}@${esc_bounce}\$/i OK"; } > /etc/postfix/bounce_recipients.regexp
  { echo "# Managed by MailFlow."; echo "${BOUNCE_DOMAIN} mailflow-bounce:"; printf '%s' "${transport_lines}"; } > /etc/postfix/transport
  # Authenticated users may only send as domains we DKIM-sign for. Both login spellings are allowed.
  dom_regex="$(all_sending_domains | sed 's/\./\\./g' | paste -sd'|' -)"
  { echo "# Managed by MailFlow."
    echo "/@(${dom_regex})\$/ ${SMTP_AUTH_USER} ${SMTP_AUTH_USER}@${SMTP_HOSTNAME}"
    # The application sets a signed VERP envelope sender (bounce+<campaign>.<recipient>.<sig>@bounce domain) so
    # bounces can be attributed. Without this line every authenticated send is rejected as "not owned by user".
    echo "/^bounce\\+[0-9]+\\.[0-9]+\\.[0-9a-f]{12}@${esc_bounce}\$/i ${SMTP_AUTH_USER} ${SMTP_AUTH_USER}@${SMTP_HOSTNAME}"; } > /etc/postfix/sender_login.regexp
  postmap /etc/postfix/transport
  chmod 644 /etc/postfix/transport /etc/postfix/transport.db /etc/postfix/bounce_recipients.regexp /etc/postfix/sender_login.regexp
fi

# ---- SASL (sasldb2): password comes from a root-only file; it is never printed -------------------------
secret_file_ensure "${SMTP_AUTH_PASSWORD_FILE}" 24
if [ "${DRY_RUN}" != "1" ]; then
  cat > /etc/postfix/sasl/smtpd.conf <<SASLEOF
pwcheck_method: auxprop
auxprop_plugin: sasldb
mech_list: PLAIN LOGIN
SASLEOF
  saslpasswd2 -c -u "${SMTP_HOSTNAME}" -p "${SMTP_AUTH_USER}" < "${SMTP_AUTH_PASSWORD_FILE}"
  chgrp postfix /etc/sasldb2; chmod 640 /etc/sasldb2
fi

# ---- aliases: postmaster/abuse go to a human ------------------------------------------------------------
if [ "${DRY_RUN}" != "1" ]; then
  sed -i '/^# BEGIN MAILFLOW$/,/^# END MAILFLOW$/d' /etc/aliases
  # Comment out stock entries we are about to define (otherwise newaliases warns about duplicates).
  sed -i -E 's/^(postmaster|abuse|root):/#(replaced by MailFlow) \1:/' /etc/aliases
  { echo "# BEGIN MAILFLOW"; echo "postmaster: ${ADMIN_EMAIL}"; echo "abuse: ${ADMIN_EMAIL}"; echo "root: ${ADMIN_EMAIL}"; echo "# END MAILFLOW"; } >> /etc/aliases
  newaliases
fi

# ---- validate BEFORE reload; roll back on failure ---------------------------------------------------------------
if [ "${DRY_RUN}" = "1" ]; then ok "dry run complete: nothing was changed."; exit 0; fi
if ! postfix check 2>/tmp/mf-postfix-check.err || [ -s /tmp/mf-postfix-check.err ]; then
  cat /tmp/mf-postfix-check.err >&2; restore_backups
  die "Postfix validation failed; previous configuration restored and Postfix was NOT reloaded."
fi
if ! postconf -n >/dev/null 2>/tmp/mf-postconf.err || grep -qi 'unused parameter\|warning' /tmp/mf-postconf.err; then
  cat /tmp/mf-postconf.err >&2; restore_backups; die "postconf reported problems; previous configuration restored."
fi
# Open-relay guard: trusted networks must be loopback ONLY, and relaying must need SASL or loopback.
non_loopback="$(postconf -h mynetworks | tr ', ' '\n\n' | grep -v '^$' | grep -vE '^(127\.|\[::1\])' || true)"
if [ -n "${non_loopback}" ] || ! postconf -h smtpd_relay_restrictions | grep -q reject_unauth_destination; then
  restore_backups; die "Safety check failed (open-relay risk: mynetworks='${non_loopback}'); previous configuration restored."
fi
systemctl enable postfix >/dev/null 2>&1 || true
if systemctl is-active --quiet postfix; then postfix reload; else systemctl start postfix; fi
sleep 1; systemctl is-active --quiet postfix || { restore_backups; systemctl restart postfix || true; die "postfix failed to start; configuration restored."; }
state_set configured yes
ok "Postfix configured. Outbound internet delivery is $( [ "$(state_get activated)" = yes ] && echo ENABLED || echo HELD until ./activate-production.sh )."
