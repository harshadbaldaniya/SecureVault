import logging

import redis
from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

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
