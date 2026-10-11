"""Rate limiting that has a defined behavior when its backing store (Redis) is unreachable.

Two policies, chosen per endpoint:

- General API throttles FAIL OPEN. If the cache cannot be reached the request proceeds and a warning is logged.
  Authorization, lockdown enforcement and auditing live in PostgreSQL, not in the cache, so nothing that protects a
  secret is lost, and (importantly) an administrator can still trigger an emergency lockdown during a Redis outage.
  The edge (nginx) rate limits do not depend on Redis and keep working.
- Credential entry points (sign-in, second factor, password reset, invitation acceptance) FAIL CLOSED. Their
  throttle and lockout counters are what stops guessing; if they cannot be read, the endpoint answers 503 instead of
  accepting unlimited attempts. Signed-in sessions are unaffected, so people keep working and responders can act.
"""

import logging

import redis
from rest_framework import throttling

logger = logging.getLogger(__name__)

# What an unreachable or misbehaving Redis looks like to Django's cache client.
CACHE_ERRORS = (redis.exceptions.RedisError, OSError)


class _FailOpen:
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except CACHE_ERRORS as exc:
            logger.warning("Rate limiting skipped because the cache is unavailable (%s)", type(exc).__name__)
            return True


class AnonRateThrottle(_FailOpen, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(_FailOpen, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(_FailOpen, throttling.ScopedRateThrottle):
    """For per-action limits such as reveal (30/minute/user)."""


class StrictScopedRateThrottle(throttling.ScopedRateThrottle):
    """For credential entry points: when the counters cannot be read, refuse rather than allow unlimited tries."""

    def allow_request(self, request, view):
        # Imported here: core.exceptions imports DRF, which reads the throttle classes from settings (a cycle).
        from core.exceptions import ServiceUnavailable

        try:
            return super().allow_request(request, view)
        except CACHE_ERRORS as exc:
            logger.error(
                "Refusing a credential-entry request because the rate-limit store is unavailable (%s)",
                type(exc).__name__,
            )
            raise ServiceUnavailable() from None
