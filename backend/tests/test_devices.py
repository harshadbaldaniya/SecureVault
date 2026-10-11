import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import UserSession
from apps.audit.models import AuditAction, AuditLog
from apps.devices.models import AnomalyAlert, Device, DeviceEvent
from apps.devices.services import hash_token
from apps.notifications.models import Notification
from apps.policies.models import policy_for

from .conftest import PASSWORD
from .vault_helpers import create_credential, dump_database_text

pytestmark = pytest.mark.django_db

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)
FP_A = "a" * 64
FP_B = "b" * 64


def register(client, fingerprint=FP_A, name="Work laptop"):
    return client.post(
        "/api/v1/devices/register/",
        {"name": name, "fingerprint": fingerprint},
        format="json",
        HTTP_USER_AGENT=CHROME_WIN,
    )


def require_device_trust(org, on=True):
    policy = policy_for(org)
    policy.require_device_trust = on
    policy.save()


def reveal(client, credential_id):
    return client.post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {}, format="json")


# --------------------------------------------------------------------------- registration and identity


def test_registration_issues_an_httponly_cookie_and_stores_only_its_hash(client_for, employee):
    client = client_for(employee)
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["trust_state"] == "PENDING" and body["os"] == "Windows" and body["browser"] == "Chrome"
    assert body["is_current"] is True

    cookie = response.cookies["sv_device"]
    assert cookie["httponly"] and cookie["samesite"] == "Strict"
    device = Device.objects.get(pk=body["id"])
    assert device.token_hash == hash_token(cookie.value)
    assert cookie.value not in dump_database_text()
    session_key = client.cookies["sv_session"].value
    assert UserSession.objects.get(session_key=session_key).device_id == device.pk


def test_registering_again_recognises_the_same_device(client_for, employee):
    client = client_for(employee)
    first = register(client).json()["id"]
    again = register(client)
    assert again.status_code == 200 and again.json()["id"] == first
    assert Device.objects.filter(user=employee).count() == 1
    assert client.get("/api/v1/devices/current/").json()["id"] == first


def test_current_device_is_404_before_registration(client_for, employee):
    assert client_for(employee).get("/api/v1/devices/current/").status_code == 404


def test_another_users_device_cookie_is_not_accepted(client_for, employee, make_user):
    colleague = make_user()
    cookie = register(client_for(colleague)).cookies["sv_device"].value
    client = client_for(employee)
    client.cookies["sv_device"] = cookie
    response = register(client)
    assert response.status_code == 201  # a new device for this user, not the colleague's
    assert Device.objects.get(pk=response.json()["id"]).user_id == employee.id


def test_changed_fingerprint_raises_a_risk_alert_but_does_not_replace_the_reference(client_for, employee):
    client = client_for(employee)
    device_id = register(client, FP_A).json()["id"]
    register(client, FP_B)
    alert = AnomalyAlert.objects.get(type="FINGERPRINT_MISMATCH")
    assert alert.severity == "MEDIUM" and str(alert.device_id) == device_id
    assert Device.objects.get(pk=device_id).fingerprint_hash == FP_A
    assert DeviceEvent.objects.filter(device_id=device_id, kind="FINGERPRINT_MISMATCH").exists()


def test_new_device_alert_only_when_the_user_already_had_one(client_for, employee):
    register(client_for(employee))
    assert not AnomalyAlert.objects.filter(type="NEW_DEVICE").exists()  # first device: nothing to compare with
    register(client_for(employee), FP_B, name="Phone")  # a fresh browser (no cookie)
    assert AnomalyAlert.objects.filter(type="NEW_DEVICE", user=employee).count() == 1
    assert Notification.objects.filter(recipient=employee, type="DEVICE_TRUST_CHANGED").count() == 2


# --------------------------------------------------------------------------- device trust gate


def test_untrusted_devices_are_blocked_when_policy_requires_trust(client_for, employee, sec_admin):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    require_device_trust(employee.organization)

    unregistered = reveal(client, credential_id)
    assert unregistered.status_code == 403 and unregistered.json()["error"]["code"] == "device_untrusted"
    alert = AnomalyAlert.objects.get(type="UNTRUSTED_DEVICE")
    assert alert.details["device_state"] == "UNREGISTERED"
    assert Notification.objects.filter(recipient=employee, type="SUSPICIOUS_ACTIVITY").exists()
    assert Notification.objects.filter(recipient=sec_admin, type="SUSPICIOUS_ACTIVITY").exists()

    device_id = register(client).json()["id"]
    assert reveal(client, credential_id).json()["error"]["code"] == "device_untrusted"  # pending is not trusted
    assert AnomalyAlert.objects.filter(type="UNTRUSTED_DEVICE").count() == 2  # deduplicated per device

    client_for(sec_admin).post(f"/api/v1/devices/{device_id}/approve/", {"reason": "Verified in person"}, format="json")
    assert reveal(client, credential_id).status_code == 200
    events = set(DeviceEvent.objects.filter(device_id=device_id).values_list("kind", flat=True))
    assert {"REGISTERED", "BLOCKED", "TRUST_CHANGED", "SENSITIVE_ACTION"} <= events


def test_device_trust_is_not_required_by_default(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    assert reveal(client, credential_id).status_code == 200


def test_suspending_a_device_signs_it_out_and_blocks_it(client_for, employee, sec_admin):
    client = client_for(employee)
    device_id = register(client).json()["id"]
    admin = client_for(sec_admin)
    admin.post(f"/api/v1/devices/{device_id}/approve/", {}, format="json")
    suspended = admin.post(f"/api/v1/devices/{device_id}/suspend/", {"reason": "Laptop reported lost"}, format="json")
    assert suspended.json()["trust_state"] == "SUSPENDED"
    assert client.get("/api/v1/auth/me/").status_code == 401  # its session was terminated
    entry = AuditLog.objects.filter(action=AuditAction.DEVICE_TRUST_CHANGE).latest("id")
    assert entry.metadata["from"] == "TRUSTED" and entry.metadata["to"] == "SUSPENDED"
    assert entry.reason == "Laptop reported lost"


def test_revoked_devices_cannot_be_trusted_again(client_for, employee, sec_admin):
    device_id = register(client_for(employee)).json()["id"]
    admin = client_for(sec_admin)
    admin.post(f"/api/v1/devices/{device_id}/revoke/", {}, format="json")
    assert admin.post(f"/api/v1/devices/{device_id}/approve/", {}, format="json").status_code == 409


def test_who_may_change_trust(client_for, employee, sec_admin, make_user):
    own_device = register(client_for(sec_admin)).json()["id"]
    response = client_for(sec_admin).post(f"/api/v1/devices/{own_device}/approve/", {}, format="json")
    assert response.json()["error"]["code"] == "self_change"  # no self-approval

    employee_device = register(client_for(employee)).json()["id"]
    assert (
        client_for(employee).post(f"/api/v1/devices/{employee_device}/approve/", {}, format="json").status_code == 403
    )
    assert (
        client_for(make_user()).post(f"/api/v1/devices/{employee_device}/revoke/", {}, format="json").status_code == 404
    )
    assert client_for(employee).post(f"/api/v1/devices/{employee_device}/revoke/", {}, format="json").status_code == 200


def test_device_lists_are_scoped(client_for, employee, sec_admin, other_admin):
    register(client_for(employee))
    register(client_for(other_admin))
    assert client_for(employee).get("/api/v1/devices/").json()["count"] == 1
    assert client_for(employee).get("/api/v1/devices/", {"scope": "all"}).json()["count"] == 1  # not an admin
    assert client_for(sec_admin).get("/api/v1/devices/", {"scope": "all"}).json()["count"] == 1  # own org only


def test_operator_break_glass_command(employee, client_for, capsys):
    device_id = register(client_for(employee)).json()["id"]
    call_command("approve_device", "--email", employee.email)
    assert device_id in capsys.readouterr().out
    call_command("approve_device", "--email", employee.email, "--device", device_id, "--reason", "Sole admin bootstrap")
    assert Device.objects.get(pk=device_id).trust_state == "TRUSTED"
    assert AuditLog.objects.filter(action=AuditAction.DEVICE_TRUST_CHANGE, metadata__via="management_command").exists()


# --------------------------------------------------------------------------- anomaly detection and review


def login_from(user, ip):
    return APIClient().post(
        "/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json", REMOTE_ADDR=ip
    )


def test_new_network_alert(employee):
    assert login_from(employee, "10.1.2.3").status_code == 200
    assert login_from(employee, "10.1.2.200").status_code == 200  # same /24: familiar
    assert not AnomalyAlert.objects.filter(type="NEW_NETWORK").exists()
    assert login_from(employee, "203.0.113.7").status_code == 200
    alert = AnomalyAlert.objects.get(type="NEW_NETWORK")
    assert alert.details == {"network": "203.0.113.0/24"} and alert.severity == "MEDIUM"


def test_reveal_burst_raises_a_high_alert(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    for _ in range(21):
        assert reveal(client, credential_id).status_code == 200
    alert = AnomalyAlert.objects.get(type="REVEAL_BURST")
    assert alert.severity == "HIGH" and alert.details["count"] == 21


def test_high_risk_hold_policy(client_for, employee, sec_admin):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    alert = AnomalyAlert.objects.create(
        organization=employee.organization, user=employee, type="REVEAL_BURST", severity="HIGH", summary="test"
    )
    assert reveal(client, credential_id).status_code == 200  # policy off: alerts inform, they do not block

    policy = policy_for(employee.organization)
    policy.block_on_high_risk = True
    policy.save()
    held = reveal(client, credential_id)
    assert held.status_code == 403 and held.json()["error"]["code"] == "risk_hold"

    review = client_for(sec_admin).post(
        f"/api/v1/alerts/{alert.pk}/dismiss/", {"note": "Expected batch job"}, format="json"
    )
    assert review.json()["status"] == "DISMISSED" and review.json()["review_note"] == "Expected batch job"
    assert AuditLog.objects.filter(action=AuditAction.ANOMALY_REVIEW).exists()
    assert reveal(client, credential_id).status_code == 200


def test_alerts_are_for_security_staff_only(client_for, employee, sec_admin, other_admin):
    AnomalyAlert.objects.create(
        organization=employee.organization, user=employee, type="NEW_DEVICE", severity="LOW", summary="mine"
    )
    AnomalyAlert.objects.create(
        organization=other_admin.organization, user=other_admin, type="NEW_DEVICE", severity="LOW", summary="theirs"
    )
    assert client_for(employee).get("/api/v1/alerts/").status_code == 403
    summaries = [a["summary"] for a in client_for(sec_admin).get("/api/v1/alerts/").json()["results"]]
    assert summaries == ["mine"]
