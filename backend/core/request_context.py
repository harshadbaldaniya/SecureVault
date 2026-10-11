"""Per-request context (request ID, client IP, user agent) for audit records and logs.

A contextvar lets service functions reach the current request's metadata without
threading `request` through every call. asgiref copies contextvars into the
worker thread that runs sync views, so this works under Daphne too.
"""

import ipaddress
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    ip_address: str | None
    user_agent: str
    request: object  # the Django HttpRequest, used to resolve the authenticated user lazily

    @property
    def user(self):
        user = getattr(self.request, "user", None)
        return user if user is not None and user.is_authenticated else None


_current: ContextVar[RequestContext | None] = ContextVar("securevault_request_context", default=None)


def current() -> RequestContext | None:
    return _current.get()


def client_ip(request) -> str | None:
    """Client IP using the same trust rule as DRF throttling (NUM_PROXIES)."""
    num_proxies = settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0
    raw = request.META.get("REMOTE_ADDR")
    if num_proxies > 0:
        forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
        if forwarded:
            raw = forwarded[-min(num_proxies, len(forwarded))]
    try:
        return ipaddress.ip_address(raw).compressed if raw else None
    except ValueError:
        return None


class RequestContextMiddleware:
    """Assigns a server-generated request ID (echoed as X-Request-ID) and captures client metadata.

    Incoming X-Request-ID headers are ignored so clients cannot forge correlation IDs in the audit log.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ctx = RequestContext(
            request_id=str(uuid.uuid4()),
            ip_address=client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            request=request,
        )
        request.request_id = ctx.request_id
        token = _current.set(ctx)
        try:
            response = self.get_response(request)
        finally:
            _current.reset(token)
        response["X-Request-ID"] = ctx.request_id
        return response
