"""
Heuristic detection of automated requests (security scanners, link
previewers, crawlers) hitting OUR OWN endpoints directly — e.g. the
unsubscribe link. This is intentionally User-Agent-based, not IP-based:
per-request IP alone (including datacenter/cloud IPs) is NOT a reliable
signal, since plenty of genuine users browse through corporate VPNs, cloud
proxies, or mobile carrier NAT that resolve to datacenter/cloud ranges too.
Flagging every datacenter IP as a bot would misclassify real people.

This does NOT (and cannot) reliably detect bots for clicks on links that
route through a third party's own click-tracking/redirect system (e.g.
Brevo's own link-click tracking on template links) — we never see the
original request for those; we only see whatever fields the third party's
webhook chooses to forward to us afterward, which may or may not include
IP/User-Agent at all.
"""
import re

# Known corporate email-security link scanners/prefetchers and generic
# bot/crawler/scripting-client signatures. Not exhaustive — scanners rotate
# and add new User-Agent strings over time — but covers the common,
# well-documented ones (Microsoft Defender for Office 365 Safe Links,
# Proofpoint URL Defense, Mimecast, Barracuda) plus generic
# scripting/automation clients.
_BOT_UA_PATTERNS = re.compile(
    r"safelink|safelinks|proofpoint|mimecast|barracuda|"
    r"bot|crawl|spider|slurp|preview|scan|"
    r"python-requests|python-urllib|curl/|wget/|libwww|http-client|"
    r"headlesschrome|phantomjs|puppeteer|playwright",
    re.IGNORECASE,
)


def looks_like_bot(user_agent):
    """
    Returns True if this User-Agent string matches a known
    scanner/bot/scripting-client pattern. An empty/missing User-Agent is
    also treated as suspicious — real browsers always send one.
    """
    if not user_agent or not user_agent.strip():
        return True
    return bool(_BOT_UA_PATTERNS.search(user_agent))


def client_ip_from_request(request):
    """
    Best-effort client IP, preferring X-Forwarded-For's first (original
    client) entry since Render sits behind a proxy — falls back to
    REMOTE_ADDR. Not authoritative (headers can be spoofed by the client
    itself if not sanitized by the proxy) — used for logging/analytics
    context only, never as a security control.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
