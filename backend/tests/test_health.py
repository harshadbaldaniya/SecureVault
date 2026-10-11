from unittest import mock

import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_reports_ok_when_dependencies_are_up():
    response = APIClient().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.django_db
def test_health_returns_503_without_leaking_error_details_when_redis_is_down():
    with mock.patch("core.views.redis.Redis.from_url", side_effect=ConnectionError("redis://secret-host:6379")):
        response = APIClient().get("/api/v1/health/")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "fail"
    assert "secret-host" not in response.content.decode()
