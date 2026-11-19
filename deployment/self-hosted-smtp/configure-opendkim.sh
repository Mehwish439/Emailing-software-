#!/usr/bin/env bash
# Install/configure OpenDKIM and create a DKIM key for every sending domain.
# Idempotent: existing keys are NEVER overwritten (that would break DNS); tables/config are re-rendered.
# Usage: sudo ./configure-opendkim.sh [--dry-run]
MF_SCRIPT="configure-opendkim"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

require_root; check_os; load_env; validate_common_env
DKIM_KEY_BITS="${DKIM_KEY_BITS:-2048}"
[[ "${DKIM_KEY_BITS}" =~ ^(1024|2048|4096)$ ]] || die "DKIM_KEY_BITS must be 1024, 2048 or 4096."

command -v opendkim >/dev/null || { log "installing opendkim"; run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq opendkim opendkim-tools; }
init_backup
for f in /etc/opendkim.conf /etc/opendkim/KeyTable /etc/opendkim/SigningTable /etc/opendkim/TrustedHosts; do backup_file "${f}"; done

run mkdir -p /etc/opendkim/keys /run/opendkim
run chown -R opendkim:opendkim /etc/opendkim
run chmod 750 /etc/opendkim /etc/opendkim/keys

render_template "${SCRIPT_DIR}/opendkim/opendkim.conf.template" /etc/opendkim.conf
render_template "${SCRIPT_DIR}/opendkim/TrustedHosts.template"  /etc/opendkim/TrustedHosts

kt_tmp="$(mktemp)"; st_tmp="$(mktemp)"; trap 'rm -f "${kt_tmp}" "${st_tmp}"' EXIT
mkdir -p /root/mailflow-dns && chmod 700 /root/mailflow-dns
while IFS= read -r DOMAIN; do
  export DOMAIN
  keydir="/etc/opendkim/keys/${DOMAIN}"
  if [ -s "${keydir}/${DKIM_SELECTOR}.private" ]; then
    log "DKIM key for ${DOMAIN} exists -- kept (never overwritten)"
  else
    log "generating ${DKIM_KEY_BITS}-bit DKIM key for ${DOMAIN} (selector ${DKIM_SELECTOR})"
    run mkdir -p "${keydir}"
    run opendkim-genkey -b "${DKIM_KEY_BITS}" -d "${DOMAIN}" -s "${DKIM_SELECTOR}" -D "${keydir}"
  fi
  run chown -R opendkim:opendkim "${keydir}"; run chmod 700 "${keydir}"
  [ "${DRY_RUN}" = "1" ] || chmod 600 "${keydir}/${DKIM_SELECTOR}.private"
  for t in KeyTable SigningTable; do
    render_template "${SCRIPT_DIR}/opendkim/${t}.template" "/tmp/mf.$$.${t}" 2>/dev/null || true
  done
  [ "${DRY_RUN}" = "1" ] || {
    grep -v '^#' "/tmp/mf.$$.KeyTable"     >> "${kt_tmp}"
    grep -v '^#' "/tmp/mf.$$.SigningTable" >> "${st_tmp}"
    rm -f "/tmp/mf.$$.KeyTable" "/tmp/mf.$$.SigningTable"
    # Public key record for DNS (the PRIVATE key never leaves /etc/opendkim/keys).
    [ -r "${keydir}/${DKIM_SELECTOR}.txt" ] && cp "${keydir}/${DKIM_SELECTOR}.txt" "/root/mailflow-dns/${DOMAIN}.dkim.txt"
  }
done < <(all_sending_domains)

if [ "${DRY_RUN}" != "1" ]; then
  install -o opendkim -g opendkim -m 640 "${kt_tmp}" /etc/opendkim/KeyTable
  install -o opendkim -g opendkim -m 640 "${st_tmp}" /etc/opendkim/SigningTable
  # Validate BEFORE (re)starting: a bad config must not take signing down.
  if ! opendkim -n -x /etc/opendkim.conf; then restore_backups; die "OpenDKIM config invalid; previous config restored, service untouched."; fi
  systemctl enable opendkim >/dev/null 2>&1 || true
  systemctl restart opendkim
  sleep 1; systemctl is-active --quiet opendkim || { restore_backups; systemctl restart opendkim || true; die "opendkim failed to start; previous config restored."; }
fi
ok "OpenDKIM configured for: $(all_sending_domains | paste -sd, -)"
log "DNS TXT records (public keys only) saved in /root/mailflow-dns/*.dkim.txt -- publish them, then run: ./validate-smtp.sh dns"
