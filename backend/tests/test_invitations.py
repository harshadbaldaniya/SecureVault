from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Invitation, User
from apps.accounts.services import hash_token

pytestmark = pytest.mark.django_db

INVITES = "/api/v1/invitations/"
ACCEPT = "/api/v1/auth/invitations/accept/"
STRONG = "Brand-New-Passphrase-77"


def invite(client, email="newbie@example.test", **extra):
    response = client.post(INVITES, {"email": email, "full_name": "New Bie", **extra}, format="json")
    assert response.status_code == 201, response.content
    data = response.json()
    return data, data["invite_url"].split("#token=", 1)[1]


def accept(token, password=STRONG):
    return APIClient().post(ACCEPT, {"token": token, "password": password}, format="json")


def test_invitation_stores_only_token_hash(client_for, admin):
    data, token = invite(client_for(admin))
    assert data["invite_url"].startswith("http://localhost:5173/accept-invite#token=")
    invitation = Invitation.objects.get(pk=data["id"])
    assert invitation.token_hash == hash_token(token)
    stored = " ".join(str(v) for v in Invitation.objects.filter(pk=invitation.pk).values().first().values())
    assert token not in stored
    user = invitation.user
    assert user.status == User.Status.INVITED
    assert not user.has_usable_password()


def test_invitation_list_never_exposes_link_or_token(client_for, admin):
    _, token = invite(client_for(admin))
    listing = client_for(admin).get(INVITES).content.decode()
    assert token not in listing
    assert "invite_url" not in listing
    assert "token_hash" not in listing


def test_accept_activates_user_who_can_then_log_in(client_for, admin):
    _, token = invite(client_for(admin))
    assert accept(token).status_code == 200
    user = User.objects.get(email="newbie@example.test")
    assert user.status == User.Status.ACTIVE
    login = APIClient().post("/api/v1/auth/login/", {"email": user.email, "password": STRONG}, format="json")
    assert login.status_code == 200


def test_token_is_single_use(client_for, admin):
    _, token = invite(client_for(admin))
    assert accept(token).status_code == 200
    second = accept(token, "Another-Passphrase-99")
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invalid_invitation"


def test_expired_token_rejected(client_for, admin):
    data, token = invite(client_for(admin))
    Invitation.objects.filter(pk=data["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert accept(token).json()["error"]["code"] == "invalid_invitation"


def test_unknown_token_rejected_with_same_message(db):
    response = accept("not-a-real-token")
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "This invitation link is invalid or has expired."


def test_weak_password_does_not_consume_invitation(client_for, admin):
    _, token = invite(client_for(admin))
    weak = accept(token, "password")
    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "weak_password"
    assert accept(token).status_code == 200


def test_revoked_invitation_cannot_be_used(client_for, admin):
    client = client_for(admin)
    data, token = invite(client)
    assert client.post(f"{INVITES}{data['id']}/revoke/").json()["state"] == "REVOKED"
    assert accept(token).status_code == 400


def test_resend_invalidates_previous_link(client_for, admin):
    client = client_for(admin)
    data, old_token = invite(client)
    resent = client.post(f"{INVITES}{data['id']}/resend/")
    assert resent.status_code == 201
    new_token = resent.json()["invite_url"].split("#token=", 1)[1]
    assert accept(old_token).status_code == 400
    assert accept(new_token).status_code == 200


def test_duplicate_email_rejected(client_for, admin, employee):
    response = client_for(admin).post(INVITES, {"email": employee.email.upper(), "full_name": "Dup"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "email_taken"


def test_deactivating_invited_user_revokes_pending_invitation(client_for, admin):
    client = client_for(admin)
    data, token = invite(client)
    user = Invitation.objects.get(pk=data["id"]).user
    assert client.patch(f"/api/v1/users/{user.id}/", {"status": "DEACTIVATED"}, format="json").status_code == 200
    assert accept(token).status_code == 400


def test_accept_requires_csrf(client_for, admin):
    _, token = invite(client_for(admin))
    response = APIClient(enforce_csrf_checks=True).post(ACCEPT, {"token": token, "password": STRONG}, format="json")
    assert response.status_code == 403
