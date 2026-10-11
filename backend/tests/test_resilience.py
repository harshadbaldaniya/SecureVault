"""Expected service failures: Redis, PostgreSQL, SMTP and the channel layer going away, and coming back.

The rule behind every case: a failure of something the request does not need must not break the request, and a failure
of something a security control needs must refuse, never silently allow.
"""

import json
import logging
import smtplib
from unittest import mock

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core import mail
from django.db import OperationalError
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetToken
from apps.audit.models import AuditAction, AuditLog
from apps.imports.models import ImportJob
from config.asgi import application
from core.metrics import WEBSOCKET_CONNECTIONS
from core.realtime import CLOSE_UNAVAILABLE

from .conftest import PASSWORD
from .test_imports import upload, workbook_bytes
from .vault_helpers import CREDENTIALS, STRONG_SECRET, create_credential

pytestmark = pytest.mark.django_db

DOWN = {"default": {"BACKEND": "tests.broken_cache.BrokenCache"}}
UP = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@pytest.fixture
def redis_down(settings):
    settings.CACHES = DOWN
    yield
    settings.CACHES = UP


# --------------------------------------------------------------------------- Redis (cache) unreachable


def test_signed_in_people_keep_working_when_the_cache_is_down(redis_down, client_for, employee, caplog):
    client = client_for(employee)
    with caplog.at_level(logging.WARNING, logger="core.throttling"):
        assert client.get("/api/v1/auth/me/").status_code == 200
        created = create_credential(client)
        assert created.status_code == 201
        revealed = client.post(f"{CREDENTIALS}{created.json()['id']}/reveal/", {"purpose": "view"}, format="json")
    assert revealed.status_code == 200 and revealed.json() == {"password": STRONG_SECRET}
    assert "Rate limiting skipped because the cache is unavailable" in caplog.text


def test_an_administrator_can_still_lock_down_during_a_cache_outage(redis_down, client_for, sec_admin, employee):
    employee_client = client_for(employee)
    credential = create_credential(employee_client).json()["id"]

    response = client_for(sec_admin).post(
        "/api/v1/lockdown/activate/",
        {"scope": "GLOBAL", "reason": "Suspected credential leak", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 201
    blocked = employee_client.post(f"{CREDENTIALS}{credential}/reveal/", {"purpose": "view"}, format="json")
    assert blocked.status_code in (401, 423)  # the lockdown is enforced from the database, not from Redis


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/auth/login/", {"email": "eve@example.test", "password": PASSWORD}),
        ("/api/v1/auth/mfa/verify/", {"code": "123456"}),
        ("/api/v1/auth/password-reset/", {"email": "eve@example.test"}),
        ("/api/v1/auth/password-reset/confirm/", {"token": "x" * 40, "new_password": PASSWORD}),
        ("/api/v1/auth/invitations/accept/", {"token": "x" * 40, "password": PASSWORD}),
    ],
)
def test_credential_entry_points_refuse_instead_of_losing_their_rate_limits(redis_down, path, body):
    response = APIClient().post(path, body, format="json")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response["Retry-After"] == "5"
    assert "redis" not in response.content.decode().lower()


def test_sign_in_is_refused_without_a_session_and_recovers_when_the_cache_returns(settings, employee):
    credentials = {"email": employee.email, "password": PASSWORD}
    settings.CACHES = DOWN
    refused = APIClient().post("/api/v1/auth/login/", credentials, format="json")
    assert refused.status_code == 503 and "sv_session" not in refused.cookies

    settings.CACHES = UP
    client = APIClient()
    assert client.post("/api/v1/auth/login/", credentials, format="json").status_code == 200
    assert client.get("/api/v1/auth/me/").status_code == 200


def test_the_lockout_counters_survive_nothing_but_never_allow_guessing_while_down(redis_down, employee):
    for _ in range(8):  # far above the lockout threshold
        response = APIClient().post(
            "/api/v1/auth/login/", {"email": employee.email, "password": "wrong-password-guess"}, format="json"
        )
        assert response.status_code == 503  # never a 400 that would let an attacker keep trying


# --------------------------------------------------------------------------- PostgreSQL unreachable


def test_a_database_outage_is_a_503_that_names_nothing(client_for, employee, caplog):
    client = client_for(employee)
    leaky = OperationalError('connection to server at "10.0.0.5", port 5432 failed: password authentication failed')
    with mock.patch("apps.departments.views.DepartmentViewSet.get_queryset", side_effect=leaky):
        with caplog.at_level(logging.ERROR):
            response = client.get("/api/v1/departments/")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "This service is temporarily unavailable. Please try again in a moment.",
        }
    }
    assert response["Retry-After"] == "5"
    assert "10.0.0.5" not in response.content.decode() and "password" not in response.content.decode()
    assert "10.0.0.5" not in caplog.text  # only the exception class is logged


def test_a_failure_before_the_view_runs_is_still_a_json_503(employee, client_for):
    """The session lookup happens in middleware, outside DRF's exception handling."""
    client = client_for(employee)
    client.raise_request_exception = False
    with mock.patch("django.contrib.sessions.backends.db.SessionStore.load", side_effect=OperationalError("down")):
        response = client.get("/api/v1/auth/me/")
    assert response.status_code == 503
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error"]["code"] == "service_unavailable"


def test_health_reports_a_database_outage_without_details():
    with mock.patch("core.views.connection.cursor", side_effect=OperationalError("host=db user=securevault")):
        response = APIClient().get("/api/v1/health/")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "fail"
    assert "securevault" not in response.content.decode()


def test_audit_write_failure_still_fails_the_action_closed(client_for, admin):
    """A sensitive action must not succeed unrecorded (existing guarantee, re-checked here under an outage)."""
    with mock.patch("apps.audit.services._append", side_effect=OperationalError("down")):
        response = client_for(admin).post("/api/v1/departments/", {"name": "Ops", "code": "OPS"}, format="json")
    assert response.status_code in (500, 503)
    assert not AuditLog.objects.filter(action=AuditAction.CREATE, target_label="Ops").exists()


# --------------------------------------------------------------------------- JSON for everything else


def test_unknown_urls_and_bad_hosts_get_the_json_envelope(client_for, employee):
    not_found = client_for(employee).get("/api/v1/no-such-endpoint/")
    assert not_found.status_code == 404 and not_found.json() == {
        "error": {"code": "not_found", "message": "Not found."}
    }
    assert not_found["Cache-Control"].startswith("no-cache") or "no-store" in not_found["Cache-Control"]

    bad_host = APIClient().get("/api/v1/health/", HTTP_HOST="evil.example")
    assert bad_host.status_code == 400
    assert json.loads(bad_host.content)["error"]["code"] == "bad_request"


# --------------------------------------------------------------------------- SMTP unreachable


def test_mail_failure_does_not_reveal_which_accounts_exist(employee, django_capture_on_commit_callbacks, caplog):
    request = "/api/v1/auth/password-reset/"
    with mock.patch("core.mail.send_mail", side_effect=smtplib.SMTPRecipientsRefused({employee.email: (550, b"no")})):
        with caplog.at_level(logging.ERROR, logger="core.mail"):
            with django_capture_on_commit_callbacks(execute=True):
                known = APIClient().post(request, {"email": employee.email}, format="json")
            with django_capture_on_commit_callbacks(execute=True):
                unknown = APIClient().post(request, {"email": "nobody@example.test"}, format="json")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert "Email delivery failed (SMTPRecipientsRefused)" in caplog.text
    assert employee.email not in caplog.text  # delivery errors can echo recipients; only the class is logged
    assert PasswordResetToken.objects.filter(user=employee).count() == 1  # the link still exists (admin can relay it)
    assert mail.outbox == []


def test_mail_failure_does_not_fail_an_import(client_for, admin, django_capture_on_commit_callbacks, caplog):
    rows = [["a@example.test", "Ann", "", ""], ["b@example.test", "Bob", "", ""]]
    with mock.patch(
        "core.mail.send_mail", side_effect=smtplib.SMTPServerDisconnected("connection unexpectedly closed")
    ):
        with caplog.at_level(logging.ERROR, logger="core.mail"):
            with django_capture_on_commit_callbacks(execute=True):
                response = upload(client_for(admin), workbook_bytes(rows))
    job = ImportJob.objects.get(pk=response.json()["id"])
    assert (job.status, job.success_count, job.failed_count) == ("COMPLETED", 2, 0)
    assert caplog.text.count("Email delivery failed (SMTPServerDisconnected)") == 2


# --------------------------------------------------------------------------- channel layer unreachable


@pytest.mark.django_db(transaction=True)
def test_websocket_closes_cleanly_when_the_channel_layer_is_down(employee, client_for):
    session = client_for(employee).cookies["sv_session"].value
    headers = [(b"origin", b"http://localhost"), (b"cookie", f"sv_session={session}".encode())]

    async def scenario():
        before = WEBSOCKET_CONNECTIONS._value.get()
        with mock.patch(
            "channels.layers.InMemoryChannelLayer.group_add", side_effect=ConnectionError("redis unreachable")
        ):
            socket = WebsocketCommunicator(application, "/ws/events/", headers=headers)
            connected, _ = await socket.connect(timeout=5)
            assert connected  # accepted only to deliver an unambiguous close code
            assert await socket.receive_output(timeout=5) == {"type": "websocket.close", "code": CLOSE_UNAVAILABLE}
            await socket.disconnect()
        assert WEBSOCKET_CONNECTIONS._value.get() == before  # never counted as an open connection

        # And it works again as soon as the layer is back.
        healthy = WebsocketCommunicator(application, "/ws/events/", headers=headers)
        connected, _ = await healthy.connect(timeout=5)
        assert connected and (await healthy.receive_json_from(timeout=5))["type"] == "hello"
        await healthy.disconnect()

    async_to_sync(scenario)()


# --------------------------------------------------------------------------- background worker


def test_one_failing_pass_does_not_stop_the_worker(tmp_path, caplog):
    from django.core.management import call_command

    heartbeat = tmp_path / "heartbeat"
    with mock.patch("apps.imports.management.commands.run_worker.run_queued", side_effect=OperationalError("db down")):
        with caplog.at_level(logging.ERROR):
            call_command("run_worker", "--once", "--heartbeat-file", str(heartbeat))
    assert "Worker pass failed; continuing" in caplog.text
    assert heartbeat.exists()  # still looping, so the container healthcheck sees a live worker
