import time

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.accounts.mfa import STEP_SECONDS
from apps.accounts.models import RecoveryCode, TOTPDevice
from apps.audit.models import AuditAction, AuditLog
from apps.policies.models import policy_for
from core.crypto import DecryptionError, decrypt_token, mfa_keyring

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

SETUP = "/api/v1/auth/mfa/totp/setup/"
CONFIRM = "/api/v1/auth/mfa/totp/confirm/"
VERIFY = "/api/v1/auth/mfa/verify/"
ME = "/api/v1/auth/me/"


def code_at(secret: str, steps_ahead: int = 0) -> str:
    step = int(time.time() // STEP_SECONDS) + steps_ahead
    return pyotp.TOTP(secret, interval=STEP_SECONDS).generate_otp(step)


def enrol(client) -> tuple[str, list[str]]:
    secret = client.post(SETUP).json()["secret"]
    response = client.post(CONFIRM, {"code": code_at(secret)}, format="json")
    assert response.status_code == 200, response.content
    return secret, response.json()["recovery_codes"]


def password_step(email: str) -> tuple[APIClient, dict]:
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    assert response.status_code == 200
    return client, response.json()


# --------------------------------------------------------------------------- enrolment


def test_setup_stores_secret_encrypted_and_bound_to_the_user(client_for, employee, admin):
    response = client_for(employee).post(SETUP)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    secret = response.json()["secret"]
    assert response.json()["otpauth_uri"].startswith("otpauth://totp/SecureVault:")

    device = TOTPDevice.objects.get(user=employee)
    assert secret not in device.secret_encrypted
    assert decrypt_token(mfa_keyring(), device.secret_encrypted, f"securevault:totp-secret:v1:{employee.pk}".encode())
    with pytest.raises(DecryptionError):  # ciphertext moved to another user's row will not decrypt
        decrypt_token(mfa_keyring(), device.secret_encrypted, f"securevault:totp-secret:v1:{admin.pk}".encode())


def test_confirm_rejects_wrong_code_and_accepts_right_one(client_for, employee):
    client = client_for(employee)
    secret = client.post(SETUP).json()["secret"]
    wrong = "000000" if code_at(secret) != "000000" else "111111"
    assert client.post(CONFIRM, {"code": wrong}, format="json").json()["error"]["code"] == "invalid_mfa_code"

    response = client.post(CONFIRM, {"code": code_at(secret)}, format="json")
    codes = response.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert response["Cache-Control"] == "no-store"
    assert client.get(ME).json()["mfa_enabled"] is True
    stored = list(RecoveryCode.objects.filter(user=employee).values_list("code_hash", flat=True))
    assert not any(code.replace("-", "") in h for code in codes for h in stored)
    assert AuditLog.objects.filter(action=AuditAction.MFA_ENROLL, actor_id=employee.id).exists()


def test_cannot_enrol_twice(client_for, employee):
    client = client_for(employee)
    enrol(client)
    assert client.post(SETUP).json()["error"]["code"] == "mfa_already_enabled"


def test_enrolling_ends_other_sessions(client_for, employee):
    other_browser = client_for(employee)
    enrol(client_for(employee))
    assert other_browser.get(ME).status_code == 401


# --------------------------------------------------------------------------- sign-in with MFA


def test_password_alone_does_not_sign_in_when_mfa_is_enabled(client_for, employee):
    enrol(client_for(employee))
    client, body = password_step(employee.email)
    assert body == {"mfa_required": True, "user": None}
    assert client.get(ME).status_code == 401


def test_totp_completes_sign_in(client_for, employee):
    secret, _ = enrol(client_for(employee))
    client, _ = password_step(employee.email)
    response = client.post(VERIFY, {"code": code_at(secret, 1)}, format="json")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == employee.email
    assert client.get(ME).status_code == 200
    login = AuditLog.objects.filter(action=AuditAction.LOGIN, outcome="SUCCESS").latest("id")
    assert login.metadata == {"second_factor": "totp"}


def test_totp_code_cannot_be_replayed(client_for, employee):
    secret, _ = enrol(client_for(employee))
    used_step = TOTPDevice.objects.get(user=employee).last_used_step
    # Replay the exact code accepted at enrolment (not "current time", which may have moved on a step).
    replayed = pyotp.TOTP(secret, interval=STEP_SECONDS).generate_otp(used_step)
    client, _ = password_step(employee.email)
    response = client.post(VERIFY, {"code": replayed}, format="json")
    assert response.json()["error"]["code"] == "invalid_mfa_code"


def test_recovery_code_works_exactly_once(client_for, employee):
    _, codes = enrol(client_for(employee))
    client, _ = password_step(employee.email)
    assert client.post(VERIFY, {"code": codes[0].upper()}, format="json").status_code == 200

    client2, _ = password_step(employee.email)
    assert client2.post(VERIFY, {"code": codes[0]}, format="json").status_code == 400


def test_verify_without_password_step_is_rejected(anon):
    response = anon.post(VERIFY, {"code": "123456"}, format="json")
    assert response.json()["error"]["code"] == "mfa_session_expired"


def test_pending_sign_in_ends_after_five_wrong_codes(client_for, employee):
    secret, _ = enrol(client_for(employee))
    client, _ = password_step(employee.email)
    for _ in range(5):
        assert client.post(VERIFY, {"code": "not-a-code"}, format="json").status_code == 400
    # Even the right code no longer works: the user must start again with the password.
    response = client.post(VERIFY, {"code": code_at(secret, 1)}, format="json")
    assert response.json()["error"]["code"] == "mfa_session_expired"


def test_pending_sign_in_expires(client_for, employee):
    secret, _ = enrol(client_for(employee))
    client, _ = password_step(employee.email)
    session = client.session
    session["mfa_pending"]["expires"] = time.time() - 1
    session.save()
    response = client.post(VERIFY, {"code": code_at(secret, 1)}, format="json")
    assert response.json()["error"]["code"] == "mfa_session_expired"


# --------------------------------------------------------------------------- disable / policy / admin reset


def test_disable_requires_password_and_code(client_for, employee):
    client = client_for(employee)
    secret, _ = enrol(client)
    bad = client.post(
        "/api/v1/auth/mfa/totp/disable/", {"password": "wrong", "code": code_at(secret, 1)}, format="json"
    )
    assert bad.json()["error"]["code"] == "reauth_failed"
    ok = client.post(
        "/api/v1/auth/mfa/totp/disable/", {"password": PASSWORD, "code": code_at(secret, 1)}, format="json"
    )
    assert ok.status_code == 204
    assert not TOTPDevice.objects.filter(user=employee).exists()


def test_policy_blocks_disabling_mfa(client_for, employee):
    client = client_for(employee)
    secret, _ = enrol(client)
    policy = policy_for(employee.organization)
    policy.require_mfa = True
    policy.save()
    response = client.post(
        "/api/v1/auth/mfa/totp/disable/", {"password": PASSWORD, "code": code_at(secret, 1)}, format="json"
    )
    assert response.json()["error"]["code"] == "mfa_required_by_policy"


def test_policy_forces_enrolment_before_other_access(client_for, employee):
    policy = policy_for(employee.organization)
    policy.require_mfa = True
    policy.save()
    client = client_for(employee)

    blocked = client.get("/api/v1/departments/")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "mfa_enrollment_required"
    assert client.get(ME).json()["mfa_enrollment_required"] is True

    enrol(client)
    assert client.get("/api/v1/departments/").status_code == 200


def test_admin_resets_lost_mfa_and_sessions_end(client_for, admin, employee):
    employee_client = client_for(employee)
    enrol(employee_client)
    assert client_for(admin).post(f"/api/v1/users/{employee.id}/reset-mfa/").status_code == 204
    assert not TOTPDevice.objects.filter(user=employee).exists()
    assert not RecoveryCode.objects.filter(user=employee).exists()
    assert employee_client.get(ME).status_code == 401
    assert AuditLog.objects.filter(action=AuditAction.MFA_RESET).exists()


def test_mfa_reset_is_admin_only_and_not_for_self(client_for, admin, employee, sec_admin):
    assert client_for(employee).post(f"/api/v1/users/{admin.id}/reset-mfa/").status_code == 403
    assert client_for(sec_admin).post(f"/api/v1/users/{employee.id}/reset-mfa/").status_code == 403
    assert client_for(admin).post(f"/api/v1/users/{admin.id}/reset-mfa/").json()["error"]["code"] == "self_change"


def test_codes_never_reach_the_audit_log(client_for, employee):
    secret, codes = enrol(client_for(employee))
    client, _ = password_step(employee.email)
    client.post(VERIFY, {"code": codes[1]}, format="json")
    text = " ".join(str(row) for row in AuditLog.objects.values_list())
    assert secret not in text
    assert not any(code in text for code in codes)
