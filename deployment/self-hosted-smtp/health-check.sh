#!/usr/bin/env bash
# Operational health of the SMTP host. Nagios-style exit codes: 0 OK, 1 WARNING, 2 CRITICAL.
# Usage: ./health-check.sh [--json] [--write]    (--write stores /var/lib/mailflow-smtp/health.json; used by the systemd timer)
set -u
MF_ETC="/etc/mailflow-smtp"; CONF="${MF_ETC}/requirements.env"
[ -r "$CONF" ] || CONF="$(dirname "$0")/requirements.env"
get() { grep -E "^$1=" "$CONF" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'; }
DISK_W="$(get HEALTH_DISK_WARN_PCT)"; DISK_W="${DISK_W:-80}"; DISK_C="$(get HEALTH_DISK_CRIT_PCT)"; DISK_C="${DISK_C:-90}"
Q_W="$(get HEALTH_QUEUE_WARN)"; Q_W="${Q_W:-500}"; Q_C="$(get HEALTH_QUEUE_CRIT)"; Q_C="${Q_C:-5000}"
CERT_W="$(get HEALTH_CERT_WARN_DAYS)"; CERT_W="${CERT_W:-14}"
status=0; msgs=(); json_items=()
raise() { [ "$1" -gt "$status" ] && status="$1"; }
note()  { msgs+=("$2"); json_items+=("\"$1\":\"$2\""); }

for s in postfix opendkim; do
  if systemctl is-active --quiet "$s"; then note "$s" "running"; else note "$s" "DOWN"; raise 2; fi
done
d_pct="$(df -P /var/spool/postfix 2>/dev/null | awk 'NR==2{gsub("%","",$5);print $5}')"; d_pct="${d_pct:-0}"
if   [ "$d_pct" -ge "$DISK_C" ]; then note disk "CRITICAL ${d_pct}% used"; raise 2
elif [ "$d_pct" -ge "$DISK_W" ]; then note disk "warning ${d_pct}% used";   raise 1
else note disk "ok ${d_pct}% used"; fi
total="$(postqueue -j 2>/dev/null | wc -l)"; deferred="$(postqueue -j 2>/dev/null | grep -c '"queue_name": *"deferred"')"
if   [ "$total" -ge "$Q_C" ]; then note queue "CRITICAL ${total} queued (${deferred} deferred)"; raise 2
elif [ "$total" -ge "$Q_W" ]; then note queue "warning ${total} queued (${deferred} deferred)";   raise 1
else note queue "ok ${total} queued (${deferred} deferred)"; fi
mem="$(free | awk '/Mem:/{printf "%d", $3/$2*100}')"; mem="${mem:-0}"
[ "$mem" -ge 90 ] && { note memory "warning ${mem}% used"; raise 1; } || note memory "ok ${mem}% used"
cert="$(postconf -h smtpd_tls_cert_file 2>/dev/null)"
if [ -n "$cert" ] && [ -r "$cert" ]; then
  days=$(( ( $(date -d "$(openssl x509 -in "$cert" -noout -enddate | cut -d= -f2)" +%s) - $(date +%s) ) / 86400 ))
  if   [ "$days" -lt 3 ];       then note cert "CRITICAL expires in ${days}d"; raise 2
  elif [ "$days" -lt "$CERT_W" ]; then note cert "warning expires in ${days}d"; raise 1
  else note cert "ok ${days}d left"; fi
else note cert "cannot read certificate"; raise 1; fi
errs="$(journalctl -u postfix --since '15 min ago' -p err --no-pager 2>/dev/null | grep -cv -- '-- No entries --' || true)"
[ "${errs:-0}" -gt 20 ] && { note errors "warning ${errs} postfix errors in 15 min"; raise 1; } || note errors "ok ${errs:-0} in 15 min"
[ -n "$(postconf -h defer_transports 2>/dev/null)" ] && note mode "HELD (pre-activation)" || note mode "live"

label=OK; [ $status -eq 1 ] && label=WARNING; [ $status -eq 2 ] && label=CRITICAL
json="{\"status\":\"${label}\",\"checked_at\":\"$(date -u +%FT%TZ)\",\"host\":\"$(hostname -f 2>/dev/null || hostname)\",$(IFS=,; echo "${json_items[*]}")}"
for a in "$@"; do
  [ "$a" = "--write" ] && { mkdir -p /var/lib/mailflow-smtp; printf '%s\n' "$json" > /var/lib/mailflow-smtp/health.json; }
done
if printf '%s\n' "$@" | grep -qx -- '--json'; then echo "$json"; else echo "${label}: ${msgs[*]}"; fi
exit $status
