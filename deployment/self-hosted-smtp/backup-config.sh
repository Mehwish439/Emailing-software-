#!/usr/bin/env bash
# Back up SMTP configuration. DKIM PRIVATE keys and secrets are EXCLUDED unless --include-secrets
# (the archive is then root-only and must be stored encrypted off-server).
# Usage: sudo ./backup-config.sh [--include-secrets]
MF_SCRIPT="backup-config"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
require_root
archive="${MF_BACKUP_ROOT}/config-$(date +%Y%m%d-%H%M%S).tar.gz"; mkdir -p "${MF_BACKUP_ROOT}"; chmod 700 "${MF_BACKUP_ROOT}"
ex=(--exclude='/etc/opendkim/keys' --exclude='/etc/mailflow-smtp/secrets' --exclude='/etc/sasldb2')
[ "${1:-}" = "--include-secrets" ] && { ex=(); warn "Including DKIM private keys and secrets -- encrypt this archive and store it OFF the server."; }
tar czf "${archive}" "${ex[@]}" /etc/postfix /etc/opendkim /etc/opendkim.conf /etc/aliases /etc/mailflow-smtp /etc/sasldb2 2>/dev/null || true
chmod 600 "${archive}"; ok "Backup written: ${archive}"
