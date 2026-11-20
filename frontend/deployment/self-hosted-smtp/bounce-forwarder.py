#!/usr/bin/env python3
"""
MailFlow bounce forwarder -- run by Postfix's `pipe` transport (user: mailflow) for every message
sent to bounce+...@<BOUNCE_DOMAIN>. Reads the raw message on stdin, signs it with HMAC-SHA256 and
POSTs it to the application's bounce intake endpoint.

Exit codes follow sysexits so Postfix does the right thing:
  0   delivered to the application (or deliberately discarded as oversized)
  75  EX_TEMPFAIL -> Postfix keeps the message queued and retries (application unreachable)
Python standard library only; no third-party dependencies.
"""
import hashlib
import hmac
import sys
import urllib.error
import urllib.request

CONF = "/etc/mailflow-smtp/bounce.conf"
MAX_BYTES = 1_000_000
EX_TEMPFAIL = 75


def load_conf(path):
    conf = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip().strip('"')
    return conf


def main():
    recipient = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        conf = load_conf(CONF)
        url = conf["BOUNCE_WEBHOOK_URL"]
        with open(conf["BOUNCE_WEBHOOK_SECRET_FILE"], encoding="utf-8") as fh:
            secret = fh.read().strip()
    except (OSError, KeyError) as exc:
        print(f"mailflow-bounce-forwarder: configuration error: {exc}", file=sys.stderr)
        return EX_TEMPFAIL
    if not secret or not url.lower().startswith("https://"):
        print("mailflow-bounce-forwarder: refusing to send: missing secret or non-HTTPS URL", file=sys.stderr)
        return EX_TEMPFAIL
    body = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        print("mailflow-bounce-forwarder: message larger than 1 MB discarded", file=sys.stderr)
        return 0
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "message/rfc822", "X-Signature": signature, "X-Envelope-Recipient": recipient,
        "User-Agent": "mailflow-bounce-forwarder/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (https enforced above)
            return 0 if 200 <= resp.status < 300 else EX_TEMPFAIL
    except urllib.error.HTTPError as exc:
        # 4xx other than 408/429 will never succeed on retry (bad signature, payload too large): drop it.
        if 400 <= exc.code < 500 and exc.code not in (408, 429):
            print(f"mailflow-bounce-forwarder: application rejected message (HTTP {exc.code}); dropped", file=sys.stderr)
            return 0
        return EX_TEMPFAIL
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"mailflow-bounce-forwarder: application unreachable: {exc}", file=sys.stderr)
        return EX_TEMPFAIL


if __name__ == "__main__":
    sys.exit(main())
