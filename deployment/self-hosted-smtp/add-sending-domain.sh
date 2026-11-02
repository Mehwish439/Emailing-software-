#!/usr/bin/env bash
# Add another domain this server will DKIM-sign and accept from authenticated clients.
# Usage: sudo ./add-sending-domain.sh example.org     (then publish the printed DKIM/SPF/DMARC DNS records)
MF_SCRIPT="add-sending-domain"
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
require_root; load_env
new="${1:-}"; [ -n "${new}" ] || die "Usage: $0 <domain>"
valid_hostname "${new}" || die "Not a valid domain: ${new}"
case ",${EXTRA_SENDING_DOMAINS:-}," in *",${new},"*) die "${new} is already configured." ;; esac
[ "${new}" != "${SENDING_DOMAIN}" ] || die "${new} is already the primary SENDING_DOMAIN."
sed -i -E "s|^EXTRA_SENDING_DOMAINS=.*|EXTRA_SENDING_DOMAINS=${EXTRA_SENDING_DOMAINS:+${EXTRA_SENDING_DOMAINS},}${new}|" "${ENV_FILE}"
"${SCRIPT_DIR}/configure-opendkim.sh"
"${SCRIPT_DIR}/configure-postfix.sh"
ok "Added ${new}. Publish /root/mailflow-dns/${new}.dkim.txt plus SPF/DMARC (see dns-records.example.txt), then: ./validate-smtp.sh dns"
