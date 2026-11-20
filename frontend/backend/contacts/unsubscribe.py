"""
One-click unsubscribe support.

Generates a signed, tamper-proof token (no extra DB table/migration needed —
django.core.signing handles integrity) encoding which contact + which
campaign an unsubscribe link is for. The token is embedded in every sent
campaign email (both in a visible "Unsubscribe" link in the body, via the
{{unsubscribe_url}} merge tag, and in the List-Unsubscribe email header —
see brevo/services.py) and resolved back by contacts/views.py's
unsubscribe_via_token view when clicked.

Using a signed token rather than a random DB-stored token keeps this
migration-free and stateless: anyone holding a valid token can unsubscribe
exactly the (contact, campaign) pair it was minted for, and nothing else.
"""
from django.core import signing

UNSUBSCRIBE_SALT = "campaign-unsubscribe-v1"


def generate_unsubscribe_token(contact_id, campaign_id=None):
    payload = {"contact_id": contact_id, "campaign_id": campaign_id}
    return signing.dumps(payload, salt=UNSUBSCRIBE_SALT)


def parse_unsubscribe_token(token):
    """Returns {"contact_id": ..., "campaign_id": ...} or raises signing.BadSignature."""
    return signing.loads(token, salt=UNSUBSCRIBE_SALT)