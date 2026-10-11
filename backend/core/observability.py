"""Per-request access log and metrics.

One structured line per request: method, URL pattern, status, duration, and the ids of the authenticated user and
organization. It deliberately omits the query string, headers, cookies and bodies (search terms and filters can be
personal, and credentials travel in bodies). Probe endpoints are counted but not logged, so health checks do not
drown the log.
"""

import logging
import time

from core import metrics
from core.request_context import current

access_log = logging.getLogger("securevault.access")

# Polled every few seconds by orchestrators; counted in metrics, not logged.
QUIET_PATHS = frozenset({"/api/v1/health/", "/api/v1/metrics/"})


def _identity(request) -> tuple[str | None, str | None]:
    """Ids of the signed-in user and organization, or (None, None). Never raises: logging must not break a request."""
    try:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return str(user.pk), str(user.organization_id)
    except Exception:  # observability must never fail the request
        return None, None
    return None, None


class ObservabilityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            return response
        finally:
            seconds = time.perf_counter() - started
            match = getattr(request, "resolver_match", None)
            route = (match.route if match is not None and match.route else None) or metrics.UNMATCHED_ROUTE
            metrics.observe_request(request.method, route, status, seconds)
            if request.path not in QUIET_PATHS:
                user_id, org_id = _identity(request)
                duration_ms = round(seconds * 1000, 1)
                ctx = current()
                access_log.info(
                    "%s %s %s %.0fms",
                    request.method,
                    route,
                    status,
                    duration_ms,
                    extra={
                        "sv": {
                            "method": request.method,
                            "route": route,
                            "status": status,
                            "duration_ms": duration_ms,
                            "user_id": user_id,
                            "org_id": org_id,
                            "ip": ctx.ip_address if ctx else None,
                        }
                    },
                )
