from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.lockdown.models import LockdownState
from apps.notifications.models import Notification

from .conftest import PASSWORD
from .vault_helpers import create_credential

pytestmark = pytest.mark.django_db

ACTIVATE = "/api/v1/lockdown/activate/"
REASON = "Suspected credential leak in #ops channel"


def activate(client, scope="GLOBAL", reason=REASON, password=PASSWORD, **extra):
    return client.post(ACTIVATE, {"scope": scope, "reason": reason, "password": password, **extra}, format="json")


def login(user, password=PASSWORD):
    return APIClient().post("/api/v1/auth/login/", {"email": user.email, "password": password}, format="json")


def reveal(client, credential_id):
    return client.post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {}, format="json")


# --------------------------------------------------------------------------- activation rules


def test_only_security_staff_can_activate(client_for, employee):
    assert activate(client_for(employee)).status_code == 403
    assert not LockdownState.objects.exists()


@pytest.mark.parametrize(
    "payload,code",
    [({"reason": "too short"}, "reason_required"), ({"password": "wrong-password"}, "reauth_failed")],
)
def test_activation_requires_a_reason_and_reauthentication(client_for, sec_admin, payload, code):
    response = activate(client_for(sec_admin), **payload)
    assert response.status_code == 400 and response.json()["error"]["code"] == code
    assert not LockdownState.objects.exists()


def test_global_lockdown_terminates_employee_sessions_and_keeps_administrators(client_for, sec_admin, employee, admin):
    employee_client = client_for(employee)
    admin_client = client_for(admin)
    response = activate(client_for(sec_admin))
    assert response.status_code == 201
    body = response.json()
    assert body["is_active"] and body["scope"] == "GLOBAL" and body["terminated_session_count"] == 1

    assert employee_client.get("/api/v1/auth/me/").status_code == 401  # session gone
    me = admin_client.get("/api/v1/auth/me/").json()
    assert me["lockdown"]["scope"] == "GLOBAL"  # administrators stay signed in to manage the incident

    entry = AuditLog.objects.get(action=AuditAction.LOCKDOWN)
    assert entry.reason == REASON and entry.metadata["operation"] == "activate"
    assert Notification.objects.filter(type="LOCKDOWN", priority="CRITICAL", recipient=employee).exists()


def test_lockdown_blocks_decryption_for_everyone_including_administrators(client_for, sec_admin, admin):
    admin_client = client_for(admin)
    credential_id = create_credential(admin_client).json()["id"]
    activate(client_for(sec_admin))
    for attempt in (
        reveal(admin_client, credential_id),
        admin_client.post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {"purpose": "copy"}, format="json"),
        admin_client.patch(f"/api/v1/vault/credentials/{credential_id}/", {"title": "x"}, format="json"),
    ):
        assert attempt.status_code == 423
        assert attempt.json()["error"]["code"] == "lockdown_active"


def test_lockdown_is_enforced_even_when_realtime_delivery_is_down(
    client_for, sec_admin, admin, django_capture_on_commit_callbacks
):
    """Acceptance check: the server blocks decryption even if no client ever receives the WebSocket event."""
    admin_client = client_for(admin)
    credential_id = create_credential(admin_client).json()["id"]
    layer = mock.Mock(side_effect=ConnectionError("redis unreachable"))
    with mock.patch("core.realtime.get_channel_layer", layer), django_capture_on_commit_callbacks(execute=True):
        assert activate(client_for(sec_admin)).status_code == 201
    assert layer.called  # the broadcast really was attempted, and its failure was contained
    assert reveal(admin_client, credential_id).status_code == 423


def test_employees_cannot_sign_in_during_a_global_lockdown(client_for, sec_admin, employee):
    activate(client_for(sec_admin))
    blocked = login(employee)
    assert blocked.status_code == 423 and blocked.json()["error"]["code"] == "lockdown_active"
    # A wrong password still gets the generic answer: the lockdown is not revealed to guessers.
    assert login(employee, "wrong-password-1").json()["error"]["code"] == "invalid_credentials"
    assert AuditLog.objects.filter(
        action=AuditAction.LOGIN, outcome=AuditOutcome.FAILURE, reason="lockdown_active"
    ).exists()
    assert login(sec_admin).status_code == 200  # administrators can still sign in to manage it


def test_a_session_that_slips_through_is_still_refused(client_for, sec_admin, employee):
    activate(client_for(sec_admin))
    sneaky = client_for(employee)  # simulates a session created after the purge (e.g. a race)
    refused = sneaky.get("/api/v1/vault/credentials/")
    assert refused.status_code == 423
    me = sneaky.get("/api/v1/auth/me/")
    assert me.status_code == 200 and me.json()["lockdown"]["scope"] == "GLOBAL"  # lets the client show why
    assert sneaky.post("/api/v1/auth/logout/").status_code == 204


def test_targeted_lockdown_affects_only_that_user(client_for, sec_admin, employee, make_user):
    colleague = make_user()
    colleague_client = client_for(colleague)
    credential_id = create_credential(colleague_client).json()["id"]
    response = activate(client_for(sec_admin), scope="USER", target_user=str(employee.id))
    assert response.status_code == 201 and response.json()["target_user_name"] == employee.full_name
    assert login(employee).status_code == 423
    assert reveal(colleague_client, credential_id).status_code == 200


def test_lockdown_conflicts_and_self_targeting(client_for, sec_admin, employee):
    client = client_for(sec_admin)
    assert activate(client, scope="USER", target_user=str(sec_admin.id)).json()["error"]["code"] == "self_change"
    assert activate(client).status_code == 201
    assert activate(client).status_code == 409


def test_mfa_users_need_a_code_to_activate(client_for, sec_admin):
    import time

    import pyotp

    from apps.accounts.mfa import STEP_SECONDS

    client = client_for(sec_admin)
    secret = client.post("/api/v1/auth/mfa/totp/setup/").json()["secret"]
    code = pyotp.TOTP(secret, interval=STEP_SECONDS).generate_otp(int(time.time() // STEP_SECONDS))
    client.post("/api/v1/auth/mfa/totp/confirm/", {"code": code}, format="json")
    assert activate(client).json()["error"]["code"] == "reauth_failed"  # password alone is not enough
    next_code = pyotp.TOTP(secret, interval=STEP_SECONDS).generate_otp(int(time.time() // STEP_SECONDS) + 1)
    assert activate(client, code=next_code).status_code == 201


# --------------------------------------------------------------------------- resolution and history


def test_resolving_restores_access(client_for, sec_admin, employee):
    admin_client = client_for(sec_admin)
    lockdown_id = activate(admin_client).json()["id"]
    assert (
        admin_client.post(
            f"/api/v1/lockdown/{lockdown_id}/resolve/", {"note": "Rotated", "password": "nope"}, format="json"
        ).json()["error"]["code"]
        == "reauth_failed"
    )
    resolved = admin_client.post(
        f"/api/v1/lockdown/{lockdown_id}/resolve/",
        {"note": "Keys rotated, all clear", "password": PASSWORD},
        format="json",
    )
    assert resolved.status_code == 200 and resolved.json()["is_active"] is False
    assert login(employee).status_code == 200
    operations = list(
        AuditLog.objects.filter(action=AuditAction.LOCKDOWN)
        .order_by("id")
        .values_list("metadata__operation", flat=True)
    )
    assert operations == ["activate", "resolve"]
    again = admin_client.post(f"/api/v1/lockdown/{lockdown_id}/resolve/", {"password": PASSWORD}, format="json")
    assert again.status_code == 409


def test_history_and_status_visibility(client_for, sec_admin, employee):
    admin_client = client_for(sec_admin)
    activate(admin_client, scope="USER", target_user=str(employee.id))
    assert admin_client.get("/api/v1/lockdown/").json()["count"] == 1
    assert client_for(employee).get("/api/v1/lockdown/").status_code in (403, 423)
    assert admin_client.get("/api/v1/lockdown/status/").json()[0]["scope"] == "USER"
