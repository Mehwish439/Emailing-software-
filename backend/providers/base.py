"""
Common interface every outbound email provider implements.

Rules the dispatcher relies on (see providers/dispatch.py):
  * send() either returns a SendResult (the provider ACCEPTED the message) or raises
    one of the three errors below -- it never returns "maybe".
  * ProviderTemporaryError  -> provider did NOT accept it; safe to retry later.
  * ProviderPermanentError  -> provider refused it for good (bad recipient, auth...).
  * ProviderAmbiguousError  -> we cannot know whether it was accepted (e.g. the
    connection died after the message body was sent). NEVER auto-retried, because a
    retry could deliver the same email twice.
  * ProviderConfigError     -> provider is not configured/usable; nothing was sent.
"""
from dataclasses import dataclass, field


class ProviderError(Exception):
    def __init__(self, message, *, code=None, raw=None):
        super().__init__(message)
        self.code = code
        self.raw = raw or {}


class ProviderConfigError(ProviderError):
    pass


class ProviderTemporaryError(ProviderError):
    pass


class ProviderPermanentError(ProviderError):
    pass


class ProviderAmbiguousError(ProviderError):
    pass


@dataclass
class OutboundEmail:
    sender_name: str
    sender_email: str
    to_email: str
    to_name: str
    subject: str
    html: str
    tags: list = field(default_factory=list)
    headers: dict = field(default_factory=dict)
    idempotency_key: str = ""
    # Envelope sender for bounces (SMTP only); "" -> provider default.
    return_path: str = ""


@dataclass
class SendResult:
    provider: str
    message_id: str
    queue_id: str = ""
    raw: dict = field(default_factory=dict)


class BaseProvider:
    name = ""

    def validate_config(self):
        """Raise ProviderConfigError if the provider cannot be used. Must not send mail."""
        raise NotImplementedError

    def send(self, email: OutboundEmail) -> SendResult:
        raise NotImplementedError

    def health(self) -> dict:
        """Cheap connectivity/auth probe. Never sends mail. Returns {ok, detail, ...}."""
        raise NotImplementedError
