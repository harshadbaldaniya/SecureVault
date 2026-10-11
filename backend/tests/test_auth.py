import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"


def login(client, email, password=PASSWORD):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def test_login_success_returns_profile_without_password(anon, employee):
    response = login(anon, employee.email)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == employee.email
    assert body["role"] == "EMPLOYEE"
    assert body["permissions"] == []
    assert "password" not in body
    assert PASSWORD not in response.content.decode()
    assert anon.get(ME).status_code == 200


def test_login_records_revocable_session(anon, employee):
    login(anon, employee.email)
    key = anon.cookies["sv_session"].value
    assert UserSession.objects.filter(session_key=key, user=employee).exists()


def test_login_rotates_session_key_to_prevent_fixation(employee):
    planted = SessionStore()
    planted.create()
    client = APIClient()
    client.cookies["sv_session"] = planted.session_key
    assert login(client, employee.email).status_code == 200
    assert client.cookies["sv_session"].value != planted.session_key


@pytest.mark.parametrize("email,password", [("user-x@example.test", PASSWORD), (None, "wrong-password-123")])
def test_bad_credentials_get_identical_generic_error(anon, employee, email, password):
    response = login(anon, email or employee.email, password)
    assert response.status_code == 400
    assert response.json()["error"] == {"code": "invalid_credentials", "message": "Invalid email or password."}


@pytest.mark.parametrize("status", [User.Status.INVITED, User.Status.SUSPENDED, User.Status.DEACTIVATED])
def test_non_active_users_cannot_log_in(anon, make_user, status):
    user = make_user(status=status)
    response = login(anon, user.email)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_lockout_after_five_failures_blocks_even_correct_password(anon, employee):
    for _ in range(5):
        assert login(anon, employee.email, "wrong-password-123").status_code == 400
    response = login(anon, employee.email)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "login_locked"


def test_lockout_applies_to_unknown_emails_too(anon):
    """Locking unknown emails the same way means lockout cannot be used to discover accounts."""
    for _ in range(5):
        login(anon, "ghost@example.test", "wrong-password-123")
    assert login(anon, "ghost@example.test").status_code == 429


def test_login_requires_csrf_token(employee):
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, employee.email).status_code == 403

    client.get("/api/v1/auth/csrf/")
    token = client.cookies["sv_csrftoken"].value
    response = client.post(
        LOGIN, {"email": employee.email, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 200


def test_authenticated_writes_require_csrf_token(admin):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf/")
    login_token = client.cookies["sv_csrftoken"].value
    client.post(LOGIN, {"email": admin.email, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=login_token)

    payload = {"name": "Ops", "code": "OPS"}
    assert client.post("/api/v1/departments/", payload, format="json").status_code == 403
    token = client.cookies["sv_csrftoken"].value  # rotated by login()
    assert token != login_token
    response = client.post("/api/v1/departments/", payload, format="json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 201


def test_unauthenticated_request_gets_401(anon):
    response = anon.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_logout_destroys_server_side_session(anon, employee):
    login(anon, employee.email)
    key = anon.cookies["sv_session"].value
    assert anon.post("/api/v1/auth/logout/").status_code == 204
    assert not Session.objects.filter(session_key=key).exists()
    assert not UserSession.objects.filter(session_key=key).exists()
    assert anon.get(ME).status_code == 401


def test_suspended_organization_blocks_login_and_existing_sessions(anon, client_for, employee, make_user):
    existing = client_for(make_user())
    employee.organization.status = "SUSPENDED"
    employee.organization.save()
    assert login(anon, employee.email).status_code == 400
    assert existing.get(ME).status_code == 403
