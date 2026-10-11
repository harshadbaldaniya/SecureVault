"""WebSocket behaviour, exercised through the real ASGI application (origin check + session auth + consumer).

transaction=True: the consumer reads the database from other threads, so data must really be committed.
Latency is measured in-process with the in-memory channel layer; the Redis-backed measurement across
processes is in docs/testing-guide.md.
"""

import time

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.lockdown import services as lockdown
from apps.notifications.services import notify
from apps.organizations.models import Organization
from config.asgi import application

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Sturdy-Test-Passphrase-42"


@pytest.fixture
def people(isolated_cache):
    org = Organization.objects.create(name="RT Ltd", slug="rt")

    def user(name, role="EMPLOYEE"):
        return User.objects.create_user(f"{name}@rt.test", org, PASSWORD, full_name=name, role=role, status="ACTIVE")

    return user("emp"), user("sec", "SEC_ADMIN")


def session_for(user) -> str:
    client = APIClient()
    client.force_login(user)
    return client.cookies["sv_session"].value


async def open_socket(session_key=None, origin=b"http://localhost"):
    headers = [(b"origin", origin)]
    if session_key:
        headers.append((b"cookie", f"sv_session={session_key}".encode()))
    communicator = WebsocketCommunicator(application, "/ws/events/", headers=headers)
    connected, code = await communicator.connect(timeout=5)
    return communicator, connected, code


def test_unauthenticated_and_cross_origin_handshakes_are_refused(people):
    employee, _ = people
    key = session_for(employee)

    async def scenario():
        # Accepted only to deliver an unambiguous close code (a rejected handshake shows up as 1006 in browsers).
        communicator, connected, _ = await open_socket(None)
        assert connected
        assert await communicator.receive_output(timeout=5) == {"type": "websocket.close", "code": 4401}
        _, connected, _ = await open_socket(key, origin=b"https://evil.example")
        assert not connected  # cross-site WebSocket hijacking: the handshake itself is rejected

    async_to_sync(scenario)()


def test_authenticated_socket_receives_hello_and_notifications(people):
    employee, _ = people
    key = session_for(employee)

    async def scenario():
        communicator, connected, _ = await open_socket(key)
        assert connected
        hello = await communicator.receive_json_from(timeout=5)
        assert hello["type"] == "hello" and hello["lockdown"] is None

        await sync_to_async(notify)([employee], "SHARE_CREATED", 'Eve shared "DB" with you')  # autocommit -> push
        message = await communicator.receive_json_from(timeout=5)
        assert message["type"] == "notification" and message["notification"]["title"] == 'Eve shared "DB" with you'

        await communicator.send_json_to({"type": "ping"})
        assert (await communicator.receive_json_from(timeout=5))["type"] == "pong"
        await communicator.disconnect()

    async_to_sync(scenario)()


def test_global_lockdown_reaches_connected_clients_in_under_a_second(people):
    employee, admin = people
    employee_key, admin_key = session_for(employee), session_for(admin)

    async def scenario():
        employee_ws, _, _ = await open_socket(employee_key)
        admin_ws, _, _ = await open_socket(admin_key)
        await employee_ws.receive_json_from(timeout=5)  # hello
        await admin_ws.receive_json_from(timeout=5)  # hello

        started = time.perf_counter()
        await sync_to_async(lockdown.activate)(
            actor=admin, scope="GLOBAL", reason="Suspected leak of DB creds", password=PASSWORD
        )
        event = await employee_ws.receive_json_from(timeout=5)
        elapsed = time.perf_counter() - started
        assert event["type"] == "lockdown.activated" and event["lockdown"]["scope"] == "GLOBAL"
        assert elapsed < 1.0, f"lockdown reached the client after {elapsed:.3f}s"

        closed = await employee_ws.receive_output(timeout=5)  # employees are disconnected
        assert closed == {"type": "websocket.close", "code": 4423}

        admin_event = await admin_ws.receive_json_from(timeout=5)  # administrators stay connected and informed
        assert admin_event["type"] == "lockdown.activated"
        await admin_ws.disconnect()

    async_to_sync(scenario)()


def test_reconnecting_during_a_lockdown_cannot_bypass_it(people):
    employee, admin = people
    lockdown.activate(
        actor=admin, scope="USER", target_user=employee, reason="Account under investigation", password=PASSWORD
    )
    old_key_was_killed = session_for(employee)  # a session created after the purge (worst case)

    async def scenario():
        communicator, connected, _ = await open_socket(old_key_was_killed)
        assert connected  # accepted only to explain why...
        message = await communicator.receive_json_from(timeout=5)
        assert message["type"] == "lockdown.active"
        assert await communicator.receive_output(timeout=5) == {
            "type": "websocket.close",
            "code": 4423,
        }  # ...then closed

    async_to_sync(scenario)()


def test_terminated_sessions_lose_their_socket(people):
    employee, admin = people
    key = session_for(employee)

    async def scenario():
        communicator, _, _ = await open_socket(key)
        await communicator.receive_json_from(timeout=5)
        from apps.accounts.services import revoke_sessions

        await sync_to_async(revoke_sessions)([employee])
        assert await communicator.receive_output(timeout=5) == {"type": "websocket.close", "code": 4401}
        retry, _, _ = await open_socket(key)  # the old session cannot reconnect
        assert await retry.receive_output(timeout=5) == {"type": "websocket.close", "code": 4401}

    async_to_sync(scenario)()
