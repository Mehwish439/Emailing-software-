#!/usr/bin/env bash
# Least-privilege firewall (ufw). Review first:  sudo ./firewall-setup.sh --dry-run
#   SSH  -> from SSH_ALLOW_FROM (or anywhere if empty)        25/tcp -> anywhere (bounce intake from the internet)
#   587  -> ONLY from APP_SERVER_IPS                          everything else inbound -> denied
# Outbound stays open (needs 25/53/80/443 for delivery, DNS, apt, certbot and the bounce forwarder).
# PostgreSQL / Redis / Postfix control ports are never opened by this script.
MF_SCRIPT="firewall-setup"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
for a in "$@"; do case "$a" in --dry-run) DRY_RUN=1 ;; --yes) ASSUME_YES=1 ;; *) die "Unknown option: $a" ;; esac; done
require_root; check_os; load_env; validate_common_env
SSH_PORT="${SSH_PORT:-22}"; [[ "${SSH_PORT}" =~ ^[0-9]+$ ]] || die "SSH_PORT must be a number."
command -v ufw >/dev/null || die "ufw not installed (apt install ufw)."

warn "Applying a firewall over SSH can lock you out. SSH (port ${SSH_PORT}) will be allowed BEFORE the firewall is enabled."
confirm "Apply these firewall rules?" || die "Cancelled."
run ufw --force reset
run ufw default deny incoming
run ufw default allow outgoing
if [ -n "${SSH_ALLOW_FROM:-}" ]; then run ufw allow from "${SSH_ALLOW_FROM}" to any port "${SSH_PORT}" proto tcp comment 'ssh (restricted)'
else warn "SSH_ALLOW_FROM is empty: SSH is open to the whole internet. Restrict it."; run ufw allow "${SSH_PORT}/tcp" comment 'ssh'; fi
run ufw allow 25/tcp comment 'smtp bounce intake'
IFS=',' read -ra ips <<< "${APP_SERVER_IPS}"
for ip in "${ips[@]}"; do ip="${ip// /}"; run ufw allow from "${ip}" to any port 587 proto tcp comment 'app submission'; done

# Let's Encrypt renewals use port 80 (standalone): open it only for the duration of each renewal.
if [ "${TLS_CERT_MODE:-letsencrypt}" = "letsencrypt" ] && [ "${DRY_RUN}" != "1" ]; then
  mkdir -p /etc/letsencrypt/renewal-hooks/pre /etc/letsencrypt/renewal-hooks/post
  printf '#!/bin/sh\nufw allow 80/tcp comment "certbot renewal" >/dev/null\n'   > /etc/letsencrypt/renewal-hooks/pre/mailflow-ufw-open.sh
  printf '#!/bin/sh\nufw delete allow 80/tcp >/dev/null 2>&1 || true\n'          > /etc/letsencrypt/renewal-hooks/post/mailflow-ufw-close.sh
  chmod 755 /etc/letsencrypt/renewal-hooks/pre/mailflow-ufw-open.sh /etc/letsencrypt/renewal-hooks/post/mailflow-ufw-close.sh
fi
run ufw logging low
run ufw --force enable
[ "${DRY_RUN}" = "1" ] || ufw status verbose
ok "Firewall applied."
