#!/usr/bin/env bash
# STAGE 3 of 3: allow real outbound delivery. Refuses to run unless DNS, TLS and relay-safety checks pass
# and you explicitly confirm that your hosting provider authorises this sending.
# Usage: sudo ./activate-production.sh [--deactivate]
MF_SCRIPT="activate-production"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
require_root; check_os; load_env; validate_common_env
[ "$(state_get configured)" = "yes" ] || die "Run ./setup-smtp.sh first."

if [ "${1:-}" = "--deactivate" ]; then
  # Emergency brake: hold all outbound delivery again (queued mail stays queued, nothing is lost).
  state_set activated no
  "${SCRIPT_DIR}/configure-postfix.sh"
  ok "Outbound delivery is HELD again. Queue preserved: postqueue -p"
  exit 0
fi

log "Running pre-activation checks (DNS, TLS, relay safety)..."
"${SCRIPT_DIR}/validate-smtp.sh" config tls relay dns || die "Validation failed. Fix the problems above, then run this again. Nothing was activated."

cat <<WARN

  You are about to ENABLE REAL OUTBOUND EMAIL from ${SMTP_HOSTNAME} (${SMTP_PUBLIC_IP}).
  Confirm each statement is TRUE:
    * Your hosting provider permits outbound port 25 from this server AND bulk/marketing email
      (many providers block port 25 or forbid marketing mail; get this in writing).
    * You will only email recipients who consented and honour unsubscribes/suppressions.
    * Rate limits in requirements.env reflect the provider's written limits.
WARN
if [ "${ASSUME_YES}" != "1" ]; then
  read -r -p "Type exactly  ACTIVATE ${SMTP_HOSTNAME}  to continue: " ans
  [ "${ans}" = "ACTIVATE ${SMTP_HOSTNAME}" ] || die "Not confirmed. Nothing was activated."
fi
state_set activated yes
"${SCRIPT_DIR}/configure-postfix.sh"
postqueue -f >/dev/null 2>&1 || true
ok "ACTIVATED. Outbound delivery is enabled. Watch it:  sudo ./health-check.sh   and   tail -f /var/log/mail.log"
log "Start with a SMALL controlled test list and low rates, then raise limits only within your provider's policy."
log "To stop everything instantly:  sudo ./activate-production.sh --deactivate"
