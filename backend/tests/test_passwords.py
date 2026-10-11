from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetToken
from apps.accounts.services import hash_token
from apps.audit.models import AuditAction, AuditLog

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

REQUEST = "/api/v1/auth/password-reset/"
CONFIRM = "/api/v1/auth/password-reset/confirm/"
CHANGE = "/api/v1/auth/password/change/"
NEW = "Fresh-Reset-Passphrase-58"


def request_reset(email: str, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return APIClient().post(REQUEST, {"email": email}, format="json")


def token_from_mail() -> str:
    body = mail.outbox[-1].body
    return body.split("#token=", 1)[1].split()[0]


def login_ok(email: str, password: str) -> bool:
    response = APIClient().post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")
    return response.status_code == 200


# --------------------------------------------------------------------------- self-service reset


def test_reset_request_answers_identically_for_known_and_unknown_emails(employee, django_capture_on_commit_callbacks):
    known = request_reset(employee.email, django_capture_on_commit_callbacks)
    unknown = request_reset("nobody@example.test", django_capture_on_commit_callbacks)
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [employee.email]


def test_reset_token_is_stored_hashed_and_resets_password(employee, client_for, django_capture_on_commit_callbacks):
    existing_session = client_for(employee)
    request_reset(employee.email, django_capture_on_commit_callbacks)
    token = token_from_mail()
    stored = PasswordResetToken.objects.get(user=employee)
    assert stored.token_hash == hash_token(token)

    response = APIClient().post(CONFIRM, {"token": token, "password": NEW}, format="json")
    assert response.status_code == 200
    assert login_ok(employee.email, NEW)
    assert not login_ok(employee.email, PASSWORD)
    assert existing_session.get("/api/v1/auth/me/").status_code == 401
    assert AuditLog.objects.filter(action=AuditAction.PASSWORD_RESET, actor_id=employee.id).exists()
    assert token not in " ".join(str(row) for row in AuditLog.objects.values_list())


def test_reset_token_is_single_use(employee, django_capture_on_commit_callbacks):
    request_reset(employee.email, django_capture_on_commit_callbacks)
    token = token_from_mail()
    assert APIClient().post(CONFIRM, {"token": token, "password": NEW}, format="json").status_code == 200
    again = APIClient().post(CONFIRM, {"token": token, "password": "Another-Passphrase-61"}, format="json")
    assert again.json()["error"]["code"] == "invalid_reset_token"


def test_expired_reset_token_is_rejected(employee, django_capture_on_commit_callbacks):
    request_reset(employee.email, django_capture_on_commit_callbacks)
    PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = APIClient().post(CONFIRM, {"token": token_from_mail(), "password": NEW}, format="json")
    assert response.json()["error"]["code"] == "invalid_reset_token"


def test_newer_request_retires_older_link(employee, django_capture_on_commit_callbacks):
    request_reset(employee.email, django_capture_on_commit_callbacks)
    first = token_from_mail()
    request_reset(employee.email, django_capture_on_commit_callbacks)
    second = token_from_mail()
    assert APIClient().post(CONFIRM, {"token": first, "password": NEW}, format="json").status_code == 400
    assert APIClient().post(CONFIRM, {"token": second, "password": NEW}, format="json").status_code == 200


def test_weak_password_does_not_consume_reset_token(employee, django_capture_on_commit_callbacks):
    request_reset(employee.email, django_capture_on_commit_callbacks)
    token = token_from_mail()
    weak = APIClient().post(CONFIRM, {"token": token, "password": "password"}, format="json")
    assert weak.json()["error"]["code"] == "weak_password"
    assert APIClient().post(CONFIRM, {"token": token, "password": NEW}, format="json").status_code == 200


def test_suspended_user_gets_no_reset_email(make_user, django_capture_on_commit_callbacks):
    user = make_user(status="SUSPENDED")
    assert request_reset(user.email, django_capture_on_commit_callbacks).status_code == 202
    assert len(mail.outbox) == 0


# --------------------------------------------------------------------------- admin-issued link


def test_admin_issues_one_time_reset_link(client_for, admin, employee):
    response = client_for(admin).post(f"/api/v1/users/{employee.id}/password-reset-link/")
    assert response.status_code == 201
    assert response["Cache-Control"] == "no-store"
    token = response.json()["reset_url"].split("#token=")[1]
    assert APIClient().post(CONFIRM, {"token": token, "password": NEW}, format="json").status_code == 200


def test_reset_link_endpoint_is_admin_only_and_not_for_self(client_for, admin, employee):
    assert client_for(employee).post(f"/api/v1/users/{admin.id}/password-reset-link/").status_code == 403
    own = client_for(admin).post(f"/api/v1/users/{admin.id}/password-reset-link/")
    assert own.json()["error"]["code"] == "self_change"


# --------------------------------------------------------------------------- password change


def test_change_password_requires_current_password(client_for, employee):
    response = client_for(employee).post(CHANGE, {"current_password": "wrong", "new_password": NEW}, format="json")
    assert response.json()["error"]["code"] == "invalid_password"
    assert login_ok(employee.email, PASSWORD)


def test_change_password_keeps_this_session_and_ends_others(client_for, employee):
    this_browser = client_for(employee)
    other_browser = client_for(employee)
    response = this_browser.post(CHANGE, {"current_password": PASSWORD, "new_password": NEW}, format="json")
    assert response.status_code == 204
    assert this_browser.get("/api/v1/auth/me/").status_code == 200
    assert other_browser.get("/api/v1/auth/me/").status_code == 401
    assert employee.sessions.count() == 1
    assert login_ok(employee.email, NEW)
    assert AuditLog.objects.filter(action=AuditAction.PASSWORD_CHANGE).exists()


def test_change_password_enforces_password_rules(client_for, employee):
    response = client_for(employee).post(
        CHANGE, {"current_password": PASSWORD, "new_password": "12345678"}, format="json"
    )
    assert response.json()["error"]["code"] == "weak_password"
