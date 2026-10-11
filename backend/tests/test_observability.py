"""Structured logs, request ids, metrics and the gated API documentation."""

import json
import logging
import re
import uuid

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient

from config.asgi import application
from core.logs import JsonFormatter, RequestIdFilter
from core.metrics import HTTP_REQUESTS, WEBSOCKET_CONNECTIONS

pytestmark = pytest.mark.django_db

ALLOWED_LOG_FIELDS = {
    "ts",
    "level",
    "logger",
    "msg",
    "request_id",
    "method",
    "route",
    "status",
    "duration_ms",
    "user_id",
    "org_id",
    "ip",
}
TOKEN = "m3trics-token-" + "x" * 30
METRICS = "/api/v1/metrics/"


def scrape(token=TOKEN):
    return APIClient().get(METRICS, HTTP_AUTHORIZATION=f"Bearer {token}")


class Capture(logging.Handler):
    """Formats records the way the production handler does (JSON + request id filter)."""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.setFormatter(JsonFormatter())
        self.addFilter(RequestIdFilter())

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture
def access_lines():
    handler = Capture()
    logger = logging.getLogger("securevault.access")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield handler.lines
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


# --------------------------------------------------------------------------- metrics endpoint


def test_metrics_endpoint_is_off_unless_a_token_is_configured(settings):
    settings.METRICS_TOKEN = ""
    assert APIClient().get(METRICS).status_code == 404
    assert APIClient().get(METRICS, HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code == 404


def test_metrics_endpoint_requires_the_bearer_token(settings):
    settings.METRICS_TOKEN = TOKEN
    for header in (None, "Bearer wrong-token", f"Basic {TOKEN}", "Bearer", TOKEN):
        extra = {"HTTP_AUTHORIZATION": header} if header else {}
        response = APIClient().get(METRICS, **extra)
        assert response.status_code == 401, header
        assert response["WWW-Authenticate"] == "Bearer"
        assert b"sv_" not in response.content
    ok = scrape()
    assert ok.status_code == 200
    assert ok["Content-Type"].startswith("text/plain")
    assert ok["Cache-Control"] == "no-store"


def test_a_session_does_not_unlock_the_metrics_endpoint(settings, client_for, admin):
    settings.METRICS_TOKEN = TOKEN
    assert client_for(admin).get(METRICS).status_code == 401  # even an organization administrator


def test_metrics_are_aggregates_without_people_or_organizations(settings, admin, employee, other_admin):
    settings.METRICS_TOKEN = TOKEN
    body = scrape().content.decode()

    assert re.search(r'^sv_users\{status="ACTIVE"\} 3\.0$', body, re.M)
    assert re.search(r'^sv_users\{status="SUSPENDED"\} 0\.0$', body, re.M)  # zero series are still present
    assert re.search(r"^sv_database_up 1\.0$", body, re.M)
    assert re.search(r'^sv_organizations\{status="ACTIVE"\} 2\.0$', body, re.M)
    for private in (admin.email, employee.email, other_admin.email, "Acme", "Globex", "Eve Employee", str(admin.pk)):
        assert private not in body


def request_total(route_contains: str, status: str) -> float:
    """Sum of the request counter for routes containing `route_contains` (the registry is process-wide)."""
    samples = [sample for metric in HTTP_REQUESTS.collect() for sample in metric.samples]
    return sum(
        sample.value
        for sample in samples
        if sample.name.endswith("_total")
        and route_contains in sample.labels["route"]
        and sample.labels["status"] == status
    )


def test_route_labels_are_url_patterns_not_ids(settings, client_for, employee):
    settings.METRICS_TOKEN = TOKEN
    client = client_for(employee)
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    detail_before = request_total("credentials/(?P<pk>", "404")
    unmatched_before = request_total("unmatched", "404")
    for credential_id in ids:
        assert client.get(f"/api/v1/vault/credentials/{credential_id}/").status_code == 404
    assert client.get("/no/such/page/").status_code == 404

    assert request_total("credentials/(?P<pk>", "404") - detail_before == 2  # both ids landed on one pattern
    assert request_total("unmatched", "404") - unmatched_before == 1
    body = scrape().content.decode()
    assert not any(credential_id in body for credential_id in ids)
    assert "no/such/page" not in body


def test_database_outage_is_reported_without_failing_the_scrape(settings, monkeypatch):
    settings.METRICS_TOKEN = TOKEN
    from apps.accounts.models import User

    def boom(*args, **kwargs):
        raise RuntimeError("postgres://user:hunter2@db/secret")

    monkeypatch.setattr(User.objects, "values_list", boom)
    response = scrape()
    assert response.status_code == 200
    body = response.content.decode()
    assert re.search(r"^sv_database_up 0\.0$", body, re.M)
    assert "hunter2" not in body


# --------------------------------------------------------------------------- access log


def test_access_log_has_route_status_and_ids_but_never_query_strings_or_credentials(access_lines, client_for, employee):
    client = client_for(employee)
    session_cookie = client.cookies["sv_session"].value
    response = client.get(
        "/api/v1/vault/credentials/?search=hunter2-private-search",
        HTTP_AUTHORIZATION="Bearer abc-secret-bearer",
        HTTP_X_API_KEY="key-in-a-header",
    )
    assert response.status_code == 200

    entry = json.loads(access_lines[-1])
    assert entry["method"] == "GET" and entry["status"] == 200
    assert "vault/credentials/" in entry["route"] and entry["duration_ms"] >= 0
    assert entry["user_id"] == str(employee.pk) and entry["org_id"] == str(employee.organization_id)
    assert entry["request_id"] == response["X-Request-ID"]
    assert set(entry) <= ALLOWED_LOG_FIELDS
    everything = "\n".join(access_lines)
    for private in ("hunter2-private-search", "abc-secret-bearer", "key-in-a-header", session_cookie):
        assert private not in everything


def test_anonymous_requests_are_logged_without_identity(access_lines):
    assert APIClient().get("/api/v1/auth/me/").status_code == 401
    entry = json.loads(access_lines[-1])
    assert entry["status"] == 401 and entry["user_id"] is None and entry["org_id"] is None


def test_health_checks_are_counted_but_not_logged(access_lines, settings):
    settings.METRICS_TOKEN = TOKEN
    APIClient().get("/api/v1/health/")
    scrape()
    assert access_lines == []
    assert 'route="api/v1/health/"' in scrape().content.decode()


def test_json_formatter_only_emits_allow_listed_fields():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.request_id = "req-1"
    record.sv = {"route": "r", "status": 200, "body": "plaintext-password", "headers": {"cookie": "sv_session=abc"}}
    record.request = object()  # what logging.getLogger("django.request").error(..., extra={"request": request}) adds
    line = JsonFormatter().format(record)
    data = json.loads(line)
    assert data["msg"] == "hello world" and data["request_id"] == "req-1" and data["route"] == "r"
    assert "plaintext-password" not in line and "sv_session" not in line and "body" not in data


def test_json_formatter_includes_the_traceback_for_errors():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    data = json.loads(JsonFormatter().format(record))
    assert data["level"] == "ERROR" and "ValueError: boom" in data["exc"]


def test_request_id_is_server_generated_and_ignores_client_supplied_ids(access_lines):
    response = APIClient().get("/api/v1/auth/me/", HTTP_X_REQUEST_ID="forged-by-client")
    assert response["X-Request-ID"] != "forged-by-client"
    assert json.loads(access_lines[-1])["request_id"] == response["X-Request-ID"]


# --------------------------------------------------------------------------- websocket gauge


@pytest.mark.django_db(transaction=True)
def test_websocket_gauge_follows_open_connections(employee, client_for):
    client = client_for(employee)
    headers = [
        (b"origin", b"http://localhost"),
        (b"cookie", f"sv_session={client.cookies['sv_session'].value}".encode()),
    ]

    async def scenario():
        before = WEBSOCKET_CONNECTIONS._value.get()
        sockets = [WebsocketCommunicator(application, "/ws/events/", headers=headers) for _ in range(2)]
        for socket in sockets:
            connected, _ = await socket.connect(timeout=5)
            assert connected
            await socket.receive_json_from(timeout=5)  # hello
        assert WEBSOCKET_CONNECTIONS._value.get() == before + 2
        await sockets[0].disconnect()
        assert WEBSOCKET_CONNECTIONS._value.get() == before + 1
        await sockets[1].disconnect()
        assert WEBSOCKET_CONNECTIONS._value.get() == before

        refused = WebsocketCommunicator(application, "/ws/events/", headers=[(b"origin", b"http://localhost")])
        await refused.connect(timeout=5)  # unauthenticated: accepted only to be closed with 4401
        await refused.receive_output(timeout=5)
        await refused.disconnect()
        assert WEBSOCKET_CONNECTIONS._value.get() == before  # refused sockets are never counted

    async_to_sync(scenario)()


# --------------------------------------------------------------------------- API documentation gate


def test_api_docs_are_hidden_when_disabled(settings, client_for, admin):
    settings.ENABLE_API_DOCS = False
    for client in (APIClient(), client_for(admin)):
        assert client.get("/api/v1/schema/").status_code == 404
        assert client.get("/api/v1/docs/").status_code == 404


def test_api_docs_require_authentication_when_enabled(settings, client_for, admin):
    settings.ENABLE_API_DOCS = True
    assert APIClient().get("/api/v1/schema/").status_code == 401
    assert APIClient().get("/api/v1/docs/").status_code == 401
    assert client_for(admin).get("/api/v1/schema/").status_code == 200


def test_the_api_only_speaks_json(client_for, admin):
    client = client_for(admin)
    html = client.get("/api/v1/auth/me/", HTTP_ACCEPT="text/html")
    assert html.status_code == 406  # no browsable-API HTML renderer
    assert client.get("/api/v1/auth/me/", HTTP_ACCEPT="*/*")["Content-Type"] == "application/json"
    form = client.post("/api/v1/departments/", {"name": "Ops", "code": "OPS"}, format="multipart")
    assert form.status_code == 415  # form-encoded bodies are not accepted on JSON endpoints
    assert client.post("/api/v1/departments/", {"name": "Ops", "code": "OPS"}, format="json").status_code == 201
