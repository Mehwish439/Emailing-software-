#!/usr/bin/env bash
# Shared helpers for the MailFlow SMTP scripts. Sourced, never executed directly.
# shellcheck shell=bash

set -Eeuo pipefail
umask 077

MF_ETC="/etc/mailflow-smtp"
MF_STATE="${MF_ETC}/state"
MF_BACKUP_ROOT="/var/backups/mailflow-smtp"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/requirements.env}"
DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_off=$'\033[0m'
[ -t 1 ] || { c_red=""; c_grn=""; c_ylw=""; c_off=""; }

log()  { printf '%s [%s] %s\n' "$(date '+%F %T')" "${MF_SCRIPT:-mailflow}" "$*"; }
ok()   { printf '%s  OK  %s %s\n' "${c_grn}" "${c_off}" "$*"; }
warn() { printf '%s WARN %s %s\n' "${c_ylw}" "${c_off}" "$*" >&2; }
fail() { printf '%s FAIL %s %s\n' "${c_red}" "${c_off}" "$*" >&2; }
die()  { fail "$*"; exit 1; }
run()  { if [ "${DRY_RUN}" = "1" ]; then log "[dry-run] $*"; else "$@"; fi; }

on_error() { fail "Aborted at line $1 (exit $2). Nothing was activated. See README 'Recovery' to roll back."; }
trap 'on_error $LINENO $?' ERR

require_root() { [ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."; }

check_os() {
  [ -r /etc/os-release ] || die "Cannot read /etc/os-release."
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] || die "This package targets Ubuntu (found: ${ID:-unknown})."
  case "${VERSION_ID:-}" in
    24.04) : ;;
    *) if [ "${ALLOW_OTHER_UBUNTU:-0}" = "1" ]; then warn "Ubuntu ${VERSION_ID} is untested (designed for 24.04)."; else
         die "Designed for Ubuntu 24.04 LTS (found ${VERSION_ID:-?}). Set ALLOW_OTHER_UBUNTU=1 to proceed at your own risk."; fi ;;
  esac
}

# Load requirements.env WITHOUT executing it (plain KEY=VALUE parsing; no command substitution).
load_env() {
  [ -f "${ENV_FILE}" ] || die "Missing ${ENV_FILE}. Copy requirements.env.example to requirements.env and edit it."
  local mode; mode="$(stat -c '%a' "${ENV_FILE}")"
  case "${mode}" in 600|400) : ;; *) warn "${ENV_FILE} has mode ${mode}; run: chmod 600 ${ENV_FILE}" ;; esac
  local line key val
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    [[ "${key}" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "Bad line in ${ENV_FILE}: ${line%%=*}"
    val="${val%\"}"; val="${val#\"}"
    declare -gx "${key}=${val}"
  done < "${ENV_FILE}"
}

require_vars() {
  local missing=() v
  for v in "$@"; do
    local val="${!v:-}"
    if [ -z "${val}" ] || [[ "${val}" == *CHANGE_ME* ]]; then missing+=("${v}"); fi
  done
  [ "${#missing[@]}" -eq 0 ] || die "Set these in ${ENV_FILE} (empty or still CHANGE_ME): ${missing[*]}"
}

valid_hostname() { [[ "$1" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$ ]]; }
valid_ipv4()     { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] && ! [[ "$1" =~ (^|\.)(25[6-9]|2[6-9][0-9]|[3-9][0-9]{2})(\.|$) ]]; }

validate_common_env() {
  require_vars SMTP_HOSTNAME SENDING_DOMAIN BOUNCE_DOMAIN ADMIN_EMAIL SMTP_PUBLIC_IP APP_SERVER_IPS SMTP_AUTH_USER DKIM_SELECTOR
  valid_hostname "${SMTP_HOSTNAME}"  || die "SMTP_HOSTNAME is not a valid hostname: ${SMTP_HOSTNAME}"
  valid_hostname "${SENDING_DOMAIN}" || die "SENDING_DOMAIN is not a valid domain: ${SENDING_DOMAIN}"
  valid_hostname "${BOUNCE_DOMAIN}"  || die "BOUNCE_DOMAIN is not a valid domain: ${BOUNCE_DOMAIN}"
  [ "${BOUNCE_DOMAIN}" != "${SENDING_DOMAIN}" ] || die "BOUNCE_DOMAIN must differ from SENDING_DOMAIN."
  valid_ipv4 "${SMTP_PUBLIC_IP}" || die "SMTP_PUBLIC_IP is not a valid IPv4 address."
  local ip; IFS=',' read -ra ips <<< "${APP_SERVER_IPS}"
  for ip in "${ips[@]}"; do ip="${ip// /}"; valid_ipv4 "${ip%%/*}" || die "APP_SERVER_IPS contains an invalid address: ${ip}"; done
  [[ "${SMTP_AUTH_USER}" =~ ^[a-z][a-z0-9_-]{2,31}$ ]] || die "SMTP_AUTH_USER must be 3-32 chars: lowercase letters, digits, - or _."
  [[ "${DKIM_SELECTOR}" =~ ^[A-Za-z0-9]{1,32}$ ]] || die "DKIM_SELECTOR must be alphanumeric."
  [[ "${GLOBAL_RATE_PER_MINUTE:-0}" =~ ^[0-9]+$ ]] || die "GLOBAL_RATE_PER_MINUTE must be a whole number."
  [[ "${DEST_CONCURRENCY:-2}" =~ ^[0-9]+$ ]] || die "DEST_CONCURRENCY must be a whole number."
  [[ "${DEST_RATE_DELAY:-1s}" =~ ^[0-9]+[smh]?$ ]] || die "DEST_RATE_DELAY must look like 1s, 500s, 2m."
  [[ "${ADMIN_EMAIL}" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || die "ADMIN_EMAIL is not a valid address."
}

all_sending_domains() {
  local d doms=("${SENDING_DOMAIN}")
  IFS=',' read -ra extra <<< "${EXTRA_SENDING_DOMAINS:-}"
  for d in "${extra[@]:-}"; do d="${d// /}"; [ -n "${d}" ] || continue
    valid_hostname "${d}" || die "EXTRA_SENDING_DOMAINS contains an invalid domain: ${d}"
    doms+=("${d}")
  done
  printf '%s\n' "${doms[@]}" | awk '!seen[$0]++'
}

# ---- backups / rollback -------------------------------------------------------
BACKUP_DIR=""
init_backup() {
  BACKUP_DIR="${MF_BACKUP_ROOT}/$(date +%Y%m%d-%H%M%S)"
  run mkdir -p "${BACKUP_DIR}"
  run chmod 700 "${MF_BACKUP_ROOT}" "${BACKUP_DIR}"
}
backup_file() {   # backup_file /etc/postfix/main.cf   (no-op if it does not exist)
  local f="$1"
  [ -e "${f}" ] || return 0
  run mkdir -p "${BACKUP_DIR}$(dirname "${f}")"
  run cp -a "${f}" "${BACKUP_DIR}${f}"
  log "backed up ${f} -> ${BACKUP_DIR}${f}"
}
restore_backups() {
  [ -n "${BACKUP_DIR}" ] && [ -d "${BACKUP_DIR}" ] || return 0
  warn "Restoring configuration from ${BACKUP_DIR}"
  (cd "${BACKUP_DIR}" && find . -type f -print0 | while IFS= read -r -d '' f; do cp -a "${f}" "/${f#./}"; done)
}

confirm() {   # confirm "Question?"  -> returns 0 for yes
  [ "${ASSUME_YES}" = "1" ] && return 0
  local ans; read -r -p "$1 [y/N] " ans; [[ "${ans}" =~ ^[Yy]$ ]]
}

# ---- templates -----------------------------------------------------------------
render_template() {  # render_template src dst  (replaces @@VAR@@ from the environment; fails on leftovers)
  local src="$1" dst="$2" content
  [ -r "${src}" ] || die "Template not found: ${src}"
  content="$(cat "${src}")"
  local var val
  # `|| true`: a template with no placeholders makes grep exit 1, which is not an error here.
  for var in $( { grep -o '@@[A-Z0-9_]*@@' "${src}" || true; } | sort -u | tr -d '@'); do
    [ -n "${!var+x}" ] || die "Template ${src} needs ${var}, which is not set."
    val="${!var}"
    content="${content//@@${var}@@/${val}}"
  done
  if grep -q '@@[A-Z0-9_]*@@' <<< "${content}"; then die "Unreplaced placeholders remain in rendered ${dst}."; fi
  if [ "${DRY_RUN}" = "1" ]; then log "[dry-run] would write ${dst}"; else printf '%s\n' "${content}" > "${dst}"; fi
}

# Single source of truth for /etc/mailflow-smtp permissions. The bounce forwarder runs as user `mailflow`, so that
# group must be able to TRAVERSE the directories (750) while each file keeps its own mode: bounce secret 640,
# SMTP auth password 600 (root only), state and env copy 600. Re-applied after every change so it cannot drift.
fix_etc_perms() {
  [ "${DRY_RUN}" = "1" ] && return 0
  local grp=root d
  getent group mailflow >/dev/null 2>&1 && grp=mailflow
  for d in "${MF_ETC}" "${MF_ETC}/secrets"; do
    [ -d "${d}" ] && { chgrp "${grp}" "${d}"; chmod 750 "${d}"; }
  done
  return 0
}

secret_file_ensure() {  # secret_file_ensure /path [bytes]  -- creates a random secret once; never prints it
  local f="$1" n="${2:-24}"
  if [ -s "${f}" ]; then log "secret exists: ${f} (kept)"; return 0; fi
  run mkdir -p "$(dirname "${f}")"; fix_etc_perms
  if [ "${DRY_RUN}" = "1" ]; then log "[dry-run] would create ${f}"; return 0; fi
  ( umask 077; head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c $((n * 2)) > "${f}" )
  chmod 600 "${f}"; log "created secret file ${f} (mode 600; contents not shown)"
}

state_get() { [ -r "${MF_STATE}" ] && grep -E "^$1=" "${MF_STATE}" | tail -1 | cut -d= -f2- || true; }
state_set() { run mkdir -p "${MF_ETC}"; fix_etc_perms
  [ "${DRY_RUN}" = "1" ] && return 0
  touch "${MF_STATE}"; chmod 600 "${MF_STATE}"
  grep -vE "^$1=" "${MF_STATE}" > "${MF_STATE}.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "${MF_STATE}.tmp"; mv "${MF_STATE}.tmp" "${MF_STATE}"; }
