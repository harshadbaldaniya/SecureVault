import hmac
import logging
import sys

import redis
from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import metrics
from core.exceptions import RETRY_AFTER_SECONDS, UNAVAILABLE, UNAVAILABLE_MESSAGE
from core.http import no_store

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Liveness/readiness probe. Reports only ok/fail per dependency, never error details."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(
        responses={
            (200, "application/json"): inline_serializer(
                "Health",
                {"status": serializers.CharField(), "checks": serializers.DictField(child=serializers.CharField())},
            )
        }
    )
    def get(self, request):
        checks = {"database": self._check_database(), "redis": self._check_redis()}
        healthy = all(value == "ok" for value in checks.values())
        return Response({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)

    @staticmethod
    def _check_database() -> str:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return "ok"
        except Exception:
            logger.exception("Health check: database unavailable")
            return "fail"

    @staticmethod
    def _check_redis() -> str:
        try:
            client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            return "ok"
        except Exception:
            logger.exception("Health check: redis unavailable")
            return "fail"


class MetricsView(APIView):
    """Prometheus metrics. Off (404) unless SV_METRICS_TOKEN is set; then it needs `Authorization: Bearer <token>`.

    Meant for a scraper on the internal network; the production nginx does not route it to the internet.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(exclude=True)
    def get(self, request):
        token = settings.METRICS_TOKEN
        if not token:
            raise Http404
        scheme, _, supplied = request.META.get("HTTP_AUTHORIZATION", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), token.encode()):
            logger.warning("Metrics request rejected: missing or wrong bearer token")
            response = HttpResponse(status=401)
            response["WWW-Authenticate"] = "Bearer"
            return no_store(response)
        body, content_type = metrics.render()
        return no_store(HttpResponse(body, content_type=content_type))


# --------------------------------------------------------------------------- JSON error pages
# Django's defaults are HTML pages. These keep the API's {"error": {...}} envelope for the cases that never reach a
# DRF view: an unknown URL, a rejected Host header, or a failure in middleware (for example the session lookup when
# the database is down).


def _json_error(code: str, message: str, http_status: int) -> JsonResponse:
    return no_store(JsonResponse({"error": {"code": code, "message": message}}, status=http_status))


def not_found(request, exception=None):
    return _json_error("not_found", "Not found.", 404)


def bad_request(request, exception=None):
    return _json_error("bad_request", "Bad request.", 400)


def permission_denied(request, exception=None):
    return _json_error("permission_denied", "You do not have permission to do this.", 403)


def server_error(request):
    """Called by Django inside the `except` block that caught the error, so sys.exc_info() still holds it."""
    error = sys.exc_info()[1]
    if isinstance(error, UNAVAILABLE):
        logger.error("A dependency was unavailable (%s)", type(error).__name__)
        response = _json_error("service_unavailable", UNAVAILABLE_MESSAGE, 503)
        response["Retry-After"] = RETRY_AFTER_SECONDS
        return response
    return _json_error("server_error", "Internal server error.", 500)
