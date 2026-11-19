#!/usr/bin/env bash
# Validate the SMTP server. Read-only except for harmless protocol probes that stop BEFORE the DATA
# command, so these tests can never send an email.
# Usage: sudo ./validate-smtp.sh [config] [tls] [relay] [dns] [queue]     (no argument or 'all' = everything)
MF_SCRIPT="validate-smtp"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
trap - ERR
set +e
require_root; load_env; validate_common_env

PASS=0; WARNS=0; FAILS=0
pass() { ok "$*"; PASS=$((PASS+1)); }
wrn()  { warn "$*"; WARNS=$((WARNS+1)); }
bad()  { fail "$*"; FAILS=$((FAILS+1)); }
modes=("$@"); [ "${#modes[@]}" -eq 0 ] && modes=(all)
want() { local m; for m in "${modes[@]}"; do [ "$m" = all ] || [ "$m" = "$1" ] && return 0; done; return 1; }
RESOLVER="${DNS_RESOLVER:-}"; dig_q() { dig +short +time=3 +tries=2 ${RESOLVER:+@"${RESOLVER}"} "$@" 2>/dev/null; }

# ------------------------------------------------------------------------------------------ config
if want config; then
  log "== configuration =="
  postfix check >/tmp/mf-check.$$ 2>&1 && [ ! -s /tmp/mf-check.$$ ] && pass "postfix check is clean" || { bad "postfix check reported: $(tr '\n' ' ' </tmp/mf-check.$$)"; }
  rm -f /tmp/mf-check.$$
  for s in postfix opendkim; do systemctl is-active --quiet "$s" && pass "$s is running" || bad "$s is NOT running (systemctl status $s)"; done
  opendkim -n -x /etc/opendkim.conf >/dev/null 2>&1 && pass "opendkim.conf parses" || bad "opendkim.conf has errors"
  command -v ss >/dev/null || bad "ss not installed (apt install iproute2)"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -q ':25$'  && pass "listening on :25 (bounce intake)" || bad "nothing listening on port 25"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -q ':587$' && pass "listening on :587 (submission)"   || bad "nothing listening on port 587"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -q '^127.0.0.1:12301$' && pass "OpenDKIM bound to loopback only" || bad "OpenDKIM milter not on 127.0.0.1:12301"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ':(5432|6379|3306)$' | grep -q . && bad "a database/Redis port is listening: do not expose these" || pass "no database/Redis ports listening"
  [ "$(postconf -h milter_default_action)" = "tempfail" ] && pass "milter_default_action=tempfail (never sends unsigned if DKIM is down)" || bad "milter_default_action is not tempfail"
  postconf -h smtpd_milters | grep -q 12301 && pass "DKIM milter wired into Postfix" || bad "smtpd_milters does not reference OpenDKIM"
  while IFS= read -r d; do
    k="/etc/opendkim/keys/${d}/${DKIM_SELECTOR}.private"
    [ -s "$k" ] && [ "$(stat -c '%a' "$k")" = "600" ] && pass "DKIM key for ${d} present, mode 600" || bad "DKIM key for ${d} missing or wrong mode ($k)"
  done < <(all_sending_domains)
  sasldblistusers2 2>/dev/null | grep -q "^${SMTP_AUTH_USER}@" && pass "SASL user ${SMTP_AUTH_USER} exists" || bad "SASL user ${SMTP_AUTH_USER} missing (re-run configure-postfix.sh)"
  [ -s "${SMTP_AUTH_PASSWORD_FILE}" ] && [ "$(stat -c '%a' "${SMTP_AUTH_PASSWORD_FILE}")" = "600" ] && pass "SMTP password file is mode 600" || bad "SMTP password file missing or not mode 600"
  if [ "$(state_get activated)" = "yes" ]; then wrn "production is ACTIVE: outbound delivery is enabled"; else pass "production not yet activated: outbound delivery is held (safe)"; fi
fi

# ----------------------------------------------------------------------------------------------- tls
if want tls; then
  log "== TLS =="
  cert="$(postconf -h smtpd_tls_cert_file)"
  if [ -r "$cert" ]; then
    openssl x509 -in "$cert" -noout -checkend 0 >/dev/null 2>&1 && pass "certificate is not expired" || bad "certificate is EXPIRED"
    days=$(( ( $(date -d "$(openssl x509 -in "$cert" -noout -enddate | cut -d= -f2)" +%s) - $(date +%s) ) / 86400 ))
    [ "$days" -ge "${HEALTH_CERT_WARN_DAYS:-14}" ] && pass "certificate valid for ${days} more days" || wrn "certificate expires in ${days} days (renew!)"
    openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null | grep -q "${SMTP_HOSTNAME}" && pass "certificate covers ${SMTP_HOSTNAME}" || bad "certificate does not list ${SMTP_HOSTNAME}"
  else bad "cannot read certificate ${cert}"; fi
  ehlo_plain="$( { printf 'EHLO probe.local\r\nQUIT\r\n'; sleep 1; } | timeout 8 openssl s_client -connect 127.0.0.1:587 -starttls smtp -quiet 2>&1 >/dev/null | head -0; printf 'EHLO probe.local\r\nQUIT\r\n' | timeout 8 nc -q1 127.0.0.1 587 2>/dev/null)"
  if grep -q "STARTTLS" <<< "$ehlo_plain"; then pass "STARTTLS offered on 587"; else bad "STARTTLS not offered on 587"; fi
  grep -qi "AUTH" <<< "$ehlo_plain" && bad "AUTH is offered BEFORE TLS (credentials could cross in clear text)" || pass "AUTH is not offered before TLS"
  tlsout="$( { printf 'EHLO probe.local\r\nQUIT\r\n'; sleep 1; } | timeout 10 openssl s_client -connect 127.0.0.1:587 -starttls smtp -servername "${SMTP_HOSTNAME}" 2>&1)"
  grep -Eq 'Protocol *: *TLSv1\.[23]' <<< "$tlsout" && pass "TLS 1.2+ negotiated" || bad "TLS 1.2+ not negotiated on 587"
  grep -qi "250.AUTH" <<< "$tlsout" && pass "AUTH offered after STARTTLS" || bad "AUTH not offered after STARTTLS"
fi

# -------------------------------------------------------------------------------------------- relay
if want relay; then
  log "== relay safety (stops before DATA; sends nothing) =="
  command -v swaks >/dev/null || bad "swaks is not installed (apt install swaks)"
  # IMPORTANT: loopback is in mynetworks (trusted by design), so a probe from 127.0.0.1 can never prove the
  # server is not an open relay. Probe from a NON-loopback address of this host instead.
  PROBE_ADDR="${RELAY_PROBE_ADDR:-$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(127\.|::1|$)' | head -1)}"
  if [ -z "${PROBE_ADDR}" ]; then
    bad "no non-loopback address found to probe from; set RELAY_PROBE_ADDR=<this host's own IP> and re-run"
  else
    log "probing from non-loopback address ${PROBE_ADDR}"
    probe="relay-probe@example.net"; from="probe@${SENDING_DOMAIN}"; pw="$(cat "${SMTP_AUTH_PASSWORD_FILE}" 2>/dev/null)"
    # swaks exit codes identify the failing protocol stage (verified against swaks 20240103): 0 ok,
    # 23 MAIL FROM rejected, 24 RCPT TO rejected, 28 AUTH failed.
    sw() { swaks --server "${PROBE_ADDR}" --quit-after "$1" "${@:2}" >/dev/null 2>&1; echo $?; }
    rc="$(sw RCPT --port 25 --from "$from" --to "$probe")"
    [ "$rc" = "24" ] && pass "port 25: relay to a third party is REJECTED at RCPT (rc=24)" || bad "port 25 may be an OPEN RELAY (rc=${rc}, expected 24)"
    rc="$(sw RCPT --port 587 --tls --from "$from" --to "$probe")"
    [ "$rc" = "23" ] || [ "$rc" = "24" ] || [ "$rc" = "28" ] && pass "port 587: unauthenticated submission is REJECTED (rc=${rc})" || bad "port 587 accepted mail WITHOUT authentication (rc=${rc})"
    rc="$(sw AUTH --port 587 --tls --auth LOGIN --auth-user "${SMTP_AUTH_USER}" --auth-password "definitely-wrong-password" --from "$from" --to "$probe")"
    [ "$rc" = "28" ] && pass "wrong password is rejected (rc=28)" || bad "wrong password was not rejected (rc=${rc})"
    rc="$(sw RCPT --port 587 --tls --auth LOGIN --auth-user "${SMTP_AUTH_USER}" --auth-password "${pw}" --from "$from" --to "$probe")"
    [ "$rc" = "0" ] && pass "authenticated submission accepted (stopped before DATA, nothing sent)" || bad "authenticated submission failed (rc=${rc})"
    rc="$(sw RCPT --port 587 --tls --auth LOGIN --auth-user "${SMTP_AUTH_USER}" --auth-password "${pw}" --from "bounce+1.2.abcdef012345@${BOUNCE_DOMAIN}" --to "$probe")"
    [ "$rc" = "0" ] && pass "authenticated client may use a VERP bounce return-path" || bad "VERP envelope sender is rejected (rc=${rc}); every campaign send would fail"
    rc="$(sw RCPT --port 587 --tls --auth LOGIN --auth-user "${SMTP_AUTH_USER}" --auth-password "${pw}" --from "spoof@not-our-domain.invalid" --to "$probe")"
    [ "$rc" = "23" ] || [ "$rc" = "24" ] && pass "sending as a domain we do not own is REJECTED (rc=${rc})" || bad "authenticated user may send as ANY domain (rc=${rc})"
    rc="$(sw RCPT --port 25 --from "x@example.net" --to "nobody@${BOUNCE_DOMAIN}")"
    [ "$rc" = "24" ] && pass "bounce domain rejects non-bounce recipients" || bad "bounce domain accepts arbitrary recipients (rc=${rc})"
    rc="$(sw RCPT --port 25 --from "x@example.net" --to "bounce+1.2.abcdef012345@${BOUNCE_DOMAIN}")"
    [ "$rc" = "0" ] && pass "bounce domain accepts VERP-shaped recipients" || bad "bounce intake rejects valid VERP-shaped recipients (rc=${rc})"
  fi
  [ "$(postconf -h smtpd_sasl_auth_enable)" = "no" ] && pass "SASL is enabled only on the submission service" || bad "SASL enabled globally"
fi

# ----------------------------------------------------------------------------------------------- dns
if want dns; then
  log "== DNS (published records vs this server) =="
  a="$(dig_q A "${SMTP_HOSTNAME}" | tail -1)"
  [ "$a" = "${SMTP_PUBLIC_IP}" ] && pass "A  ${SMTP_HOSTNAME} -> ${a}" || bad "A  ${SMTP_HOSTNAME} is '${a:-missing}', expected ${SMTP_PUBLIC_IP}"
  rev="$(dig_q -x "${SMTP_PUBLIC_IP}" | tail -1 | sed 's/\.$//')"
  if [ "$rev" = "${SMTP_HOSTNAME}" ]; then pass "PTR ${SMTP_PUBLIC_IP} -> ${rev} (forward-confirmed)"
  else bad "PTR (rDNS) for ${SMTP_PUBLIC_IP} is '${rev:-missing}', must be ${SMTP_HOSTNAME} -- set it in your hosting provider's panel"; fi
  mx="$(dig_q MX "${BOUNCE_DOMAIN}" | awk '{print $2}' | sed 's/\.$//' | head -1)"
  [ "$mx" = "${SMTP_HOSTNAME}" ] && pass "MX ${BOUNCE_DOMAIN} -> ${mx}" || bad "MX for ${BOUNCE_DOMAIN} is '${mx:-missing}', expected ${SMTP_HOSTNAME}"
  while IFS= read -r d; do
    spf="$(dig_q TXT "$d" | tr -d '"' | grep -i '^v=spf1' | head -1)"
    if [ -z "$spf" ]; then bad "SPF TXT missing at ${d}"
    elif grep -q "ip4:${SMTP_PUBLIC_IP}" <<< "$spf" || grep -qE '(^| )(a|mx)( |$)' <<< "$spf"; then pass "SPF at ${d} authorises this server: ${spf}"
    else bad "SPF at ${d} does not include ip4:${SMTP_PUBLIC_IP}: ${spf}"; fi
    grep -qE '[~-]all' <<< "$spf" || { [ -n "$spf" ] && wrn "SPF at ${d} does not end in ~all or -all"; }
    pub_local="$(tr -d '\n\t "()' < "/etc/opendkim/keys/${d}/${DKIM_SELECTOR}.txt" 2>/dev/null | grep -o 'p=[A-Za-z0-9+/=]*' | head -1)"
    pub_dns="$(dig_q TXT "${DKIM_SELECTOR}._domainkey.${d}" | tr -d '\n\t "()' | grep -o 'p=[A-Za-z0-9+/=]*' | head -1)"
    if [ -z "$pub_dns" ]; then bad "DKIM TXT missing at ${DKIM_SELECTOR}._domainkey.${d}"
    elif [ "$pub_local" = "$pub_dns" ]; then pass "DKIM at ${d} matches the server's key"
    else bad "DKIM at ${d} does not match the server's public key (re-publish /root/mailflow-dns/${d}.dkim.txt)"; fi
    dm="$(dig_q TXT "_dmarc.${d}" | tr -d '"' | grep -i '^v=DMARC1' | head -1)"
    if [ -z "$dm" ]; then bad "DMARC TXT missing at _dmarc.${d}"
    else pass "DMARC at ${d}: ${dm}"; grep -qi 'p=none' <<< "$dm" && wrn "DMARC p=none at ${d}: monitoring only; move to quarantine/reject once SPF+DKIM align"; fi
  done < <(all_sending_domains)
  if timeout 6 bash -c 'exec 3<>/dev/tcp/gmail-smtp-in.l.google.com/25' 2>/dev/null; then pass "outbound port 25 is reachable from this server"
  else bad "outbound port 25 appears BLOCKED (many hosts block it). Ask your provider before going live."; fi
fi

# --------------------------------------------------------------------------------------------- queue
if want queue; then
  log "== queue =="
  total="$(postqueue -j 2>/dev/null | wc -l)"; deferred="$(postqueue -j 2>/dev/null | grep -c '"queue_name": *"deferred"')"
  log "messages in queue: ${total} (deferred: ${deferred})"
  [ "${total}" -lt "${HEALTH_QUEUE_WARN:-500}" ] && pass "queue size is normal" || wrn "queue has ${total} messages"
  if [ "${total}" -gt 0 ]; then log "recent reasons (postqueue -p):"; postqueue -p 2>/dev/null | grep -E '^\s+\(' | sort | uniq -c | sort -rn | head -5; fi
  [ -n "$(postconf -h defer_transports)" ] && log "note: defer_transports is set -> outbound delivery is intentionally held (pre-activation)"
fi

echo; log "Result: ${PASS} passed, ${WARNS} warning(s), ${FAILS} FAILED"
[ "${FAILS}" -eq 0 ]
