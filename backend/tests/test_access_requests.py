from datetime import timedelta

import pytest
from django.utils import timezone

from apps.access_requests.models import AccessRequest
from apps.audit.models import AuditAction, AuditLog
from apps.notifications.models import Notification
from apps.sharing.models import Share

from .vault_helpers import STRONG_SECRET, create_credential

pytestmark = pytest.mark.django_db

REQUESTS = "/api/v1/access-requests/"


@pytest.fixture
def setup(client_for, employee, make_user):
    owner_client = client_for(employee)
    credential_id = create_credential(owner_client, title="Payroll DB").json()["id"]
    owner_client.patch(f"/api/v1/vault/credentials/{credential_id}/", {"requestable": True}, format="json")
    return employee, make_user(full_name="Requester Rita"), credential_id


def ask(client, credential_id, hours=8, permission="VIEW", reason="Quarterly payroll run"):
    return client.post(
        REQUESTS,
        {"credential": credential_id, "duration_hours": hours, "permission": permission, "reason": reason},
        format="json",
    )


def test_directory_lists_only_opted_in_credentials_and_only_metadata(client_for, setup):
    owner, rita, credential_id = setup
    create_credential(client_for(owner), title="Private thing")  # not requestable
    entries = client_for(rita).get("/api/v1/vault/directory/").json()["results"]
    assert [e["title"] for e in entries] == ["Payroll DB"]
    assert set(entries[0]) == {"id", "title", "service_name", "category", "owner_name"}  # no username, no secret
    assert client_for(owner).get("/api/v1/vault/directory/").json()["count"] == 0  # own credentials excluded


def test_request_notifies_owner_and_is_audited(client_for, setup):
    owner, rita, credential_id = setup
    response = ask(client_for(rita), credential_id)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "PENDING" and body["owner_name"] == owner.full_name
    assert Notification.objects.filter(recipient=owner, type="ACCESS_REQUEST").exists()
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_REQUEST, actor_id=rita.id).exists()


@pytest.mark.parametrize(
    "case,expected",
    [("duplicate", 409), ("not_requestable", 404), ("own", 409), ("too_long", 400), ("bad_reason", 400)],
)
def test_invalid_requests_are_rejected(client_for, setup, case, expected):
    owner, rita, credential_id = setup
    rita_client = client_for(rita)
    if case == "duplicate":
        ask(rita_client, credential_id)
        response = ask(rita_client, credential_id)
    elif case == "not_requestable":
        private = create_credential(client_for(owner), title="Private").json()["id"]
        response = ask(rita_client, private)
    elif case == "own":
        response = ask(client_for(owner), credential_id)
    elif case == "too_long":
        response = ask(rita_client, credential_id, hours=30 * 24 + 1)
    else:
        response = ask(rita_client, credential_id, reason="x")
    assert response.status_code == expected


def test_owner_approves_and_requester_gets_a_time_bound_grant(client_for, setup):
    owner, rita, credential_id = setup
    request_id = ask(client_for(rita), credential_id, hours=8).json()["id"]

    approved = client_for(owner).post(f"{REQUESTS}{request_id}/approve/", {"duration_hours": 4}, format="json")
    assert approved.status_code == 200 and approved.json()["state"] == "APPROVED"
    share = Share.objects.get(pk=approved.json()["share"])
    assert share.grantee_id == rita.id and share.permission == "VIEW"
    assert abs((share.expires_at - timezone.now()) - timedelta(hours=4)) < timedelta(minutes=1)

    reveal = client_for(rita).post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {}, format="json")
    assert reveal.json() == {"password": STRONG_SECRET}
    assert Notification.objects.filter(recipient=rita, type="ACCESS_APPROVED").exists()
    assert AuditLog.objects.filter(action=AuditAction.APPROVAL, actor_id=owner.id).exists()

    again = client_for(owner).post(f"{REQUESTS}{request_id}/approve/", {}, format="json")
    assert again.status_code == 409


def test_approval_cannot_exceed_the_request(client_for, setup):
    owner, rita, credential_id = setup
    request_id = ask(client_for(rita), credential_id, hours=8, permission="VIEW").json()["id"]
    owner_client = client_for(owner)
    assert (
        owner_client.post(f"{REQUESTS}{request_id}/approve/", {"permission": "EDIT"}, format="json").status_code == 400
    )
    assert (
        owner_client.post(f"{REQUESTS}{request_id}/approve/", {"duration_hours": 9}, format="json").status_code == 400
    )
    assert not Share.objects.exists()


def test_only_the_owner_can_decide(client_for, setup, admin):
    owner, rita, credential_id = setup
    request_id = ask(client_for(rita), credential_id).json()["id"]
    assert (
        client_for(admin).post(f"{REQUESTS}{request_id}/approve/", {}, format="json").status_code == 404
    )  # not even visible
    assert client_for(rita).post(f"{REQUESTS}{request_id}/approve/", {}, format="json").status_code == 403
    assert not Share.objects.exists()


def test_reject_and_cancel(client_for, setup, make_user):
    owner, rita, credential_id = setup
    rita_client = client_for(rita)
    first = ask(rita_client, credential_id).json()["id"]
    rejected = client_for(owner).post(
        f"{REQUESTS}{first}/reject/", {"note": "Use the reporting replica"}, format="json"
    )
    assert rejected.json()["state"] == "REJECTED" and rejected.json()["decision_note"] == "Use the reporting replica"
    assert Notification.objects.filter(recipient=rita, type="ACCESS_REJECTED").exists()
    assert AuditLog.objects.filter(action=AuditAction.REJECTION).exists()

    second = ask(rita_client, credential_id).json()["id"]
    assert client_for(owner).post(f"{REQUESTS}{second}/cancel/").status_code == 403  # only the requester
    assert rita_client.post(f"{REQUESTS}{second}/cancel/").json()["state"] == "CANCELLED"


def test_lapsed_pending_requests_cannot_be_approved_and_free_the_slot(client_for, setup):
    owner, rita, credential_id = setup
    request_id = ask(client_for(rita), credential_id).json()["id"]
    AccessRequest.objects.filter(pk=request_id).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client_for(owner).get(f"{REQUESTS}{request_id}/").json()["state"] == "EXPIRED"
    assert client_for(owner).post(f"{REQUESTS}{request_id}/approve/", {}, format="json").status_code == 409
    assert ask(client_for(rita), credential_id).status_code == 201  # a new request is possible


def test_mailboxes(client_for, setup):
    owner, rita, credential_id = setup
    ask(client_for(rita), credential_id)
    assert client_for(rita).get(REQUESTS, {"box": "mine"}).json()["count"] == 1
    assert client_for(rita).get(REQUESTS, {"box": "to_approve"}).json()["count"] == 0
    assert client_for(owner).get(REQUESTS, {"box": "to_approve"}).json()["count"] == 1


def test_requester_with_access_cannot_request_again(client_for, setup):
    owner, rita, credential_id = setup
    request_id = ask(client_for(rita), credential_id).json()["id"]
    client_for(owner).post(f"{REQUESTS}{request_id}/approve/", {}, format="json")
    assert ask(client_for(rita), credential_id).json()["error"]["code"] == "already_has_access"
    assert ask(client_for(rita), credential_id, permission="EDIT").status_code == 201  # asking for more is fine
