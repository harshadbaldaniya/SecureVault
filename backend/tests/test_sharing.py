from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.utils import timezone

from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.notifications.models import Notification
from apps.policies.models import policy_for
from apps.sharing.models import Share

from .vault_helpers import STRONG_SECRET, create_credential

pytestmark = pytest.mark.django_db


def share_url(cid):
    return f"/api/v1/vault/credentials/{cid}/share/"


def reveal_url(cid):
    return f"/api/v1/vault/credentials/{cid}/reveal/"


@pytest.fixture
def people(make_user, employee):
    return SimpleNamespace(
        owner=employee,
        bob=make_user(full_name="Bob"),
        carol=make_user(full_name="Carol"),
        dave=make_user(full_name="Dave"),
    )


@pytest.fixture
def cred(client_for, people):
    return create_credential(client_for(people.owner)).json()["id"]


def give(client, cid, grantee, permission="VIEW", **extra):
    return client.post(share_url(cid), {"grantee": str(grantee.id), "permission": permission, **extra}, format="json")


def reveal(client, cid, purpose="view"):
    return client.post(reveal_url(cid), {"purpose": purpose}, format="json")


# --------------------------------------------------------------------------- permission levels


def test_view_grant_allows_reveal_and_copy_only(client_for, people, cred):
    response = give(client_for(people.owner), cred, people.bob, "VIEW")
    assert response.status_code == 201
    assert response.json()["state"] == "ACTIVE" and response.json()["depth"] == 0

    bob = client_for(people.bob)
    listed = bob.get("/api/v1/vault/credentials/", {"scope": "shared"}).json()["results"]
    assert [c["id"] for c in listed] == [cred]
    assert listed[0]["access"] == "shared" and listed[0]["reuse_count"] == 0
    assert listed[0]["sharing"]["permission"] == "VIEW" and listed[0]["sharing"]["shared_by"] == people.owner.full_name
    assert listed[0]["permissions"] == ["COPY", "REVEAL", "VIEW"]

    assert reveal(bob, cred).json() == {"password": STRONG_SECRET}
    assert reveal(bob, cred, "copy").status_code == 200
    assert bob.patch(f"/api/v1/vault/credentials/{cred}/", {"title": "x"}, format="json").status_code == 403
    assert bob.delete(f"/api/v1/vault/credentials/{cred}/").status_code == 403
    assert give(bob, cred, people.carol).status_code == 403


def test_edit_grant_allows_editing_but_not_sharing_deleting_or_owner_settings(client_for, people, cred):
    give(client_for(people.owner), cred, people.bob, "EDIT")
    bob = client_for(people.bob)
    assert (
        bob.patch(f"/api/v1/vault/credentials/{cred}/", {"title": "Renamed by Bob"}, format="json").status_code == 200
    )
    assert (
        bob.patch(
            f"/api/v1/vault/credentials/{cred}/", {"password": "Zk4#Rotated-By-Bob-77"}, format="json"
        ).status_code
        == 200
    )
    assert reveal(client_for(people.owner), cred).json()["password"] == "Zk4#Rotated-By-Bob-77"
    owner_only = bob.patch(f"/api/v1/vault/credentials/{cred}/", {"requestable": True}, format="json")
    assert owner_only.status_code == 403 and owner_only.json()["error"]["code"] == "owner_only"
    assert bob.delete(f"/api/v1/vault/credentials/{cred}/").status_code == 403
    assert give(bob, cred, people.carol).status_code == 403


def test_share_grant_can_delegate_within_its_own_bounds(client_for, people, cred):
    owner_share = give(
        client_for(people.owner), cred, people.bob, "SHARE", expires_at=(timezone.now() + timedelta(days=5)).isoformat()
    ).json()
    bob = client_for(people.bob)

    too_long = give(bob, cred, people.carol, "VIEW", expires_at=(timezone.now() + timedelta(days=6)).isoformat())
    assert too_long.status_code == 400 and too_long.json()["error"]["code"] == "exceeds_upstream"

    child = give(bob, cred, people.carol, "EDIT")
    assert child.status_code == 201
    child = child.json()
    assert child["parent_share"] == owner_share["id"] and child["depth"] == 1
    assert child["expires_at"] == owner_share["expires_at"]  # defaults to the upstream expiry, never beyond

    assert give(bob, cred, people.carol, "VIEW").json()["error"]["code"] == "already_shared"
    assert give(client_for(people.carol), cred, people.dave).status_code == 403  # EDIT cannot delegate


def test_delegation_depth_is_limited(client_for, make_user, people, cred):
    chain = [people.owner] + [make_user(full_name=f"Level {i}") for i in range(7)]
    for level in range(6):
        response = give(client_for(chain[level]), cred, chain[level + 1], "SHARE")
        assert response.status_code == 201, (level, response.content)
        assert response.json()["depth"] == level
    too_deep = give(client_for(chain[6]), cred, chain[7], "VIEW")
    assert too_deep.status_code == 400 and too_deep.json()["error"]["code"] == "too_deep"


@pytest.mark.parametrize("target", ["self", "owner", "other_org", "suspended"])
def test_invalid_grantees_are_rejected(client_for, people, cred, other_admin, make_user, target):
    owner_client = client_for(people.owner)
    if target == "owner":
        give(owner_client, cred, people.bob, "SHARE")
        response = give(client_for(people.bob), cred, people.owner)
    else:
        grantee = {"self": people.owner, "other_org": other_admin, "suspended": make_user(status="SUSPENDED")}[target]
        response = give(owner_client, cred, grantee)
    assert response.status_code == 400
    assert not Share.objects.filter(grantee__in=[other_admin]).exists()


def test_expiry_defaults_to_policy_and_cannot_exceed_it_or_be_in_the_past(client_for, people, cred):
    owner = client_for(people.owner)
    created = give(owner, cred, people.bob).json()
    expires = timezone.datetime.fromisoformat(created["expires_at"])
    assert abs((expires - timezone.now()) - timedelta(days=30)) < timedelta(minutes=1)

    over = give(owner, cred, people.carol, expires_at=(timezone.now() + timedelta(days=31)).isoformat())
    assert over.json()["error"]["code"] == "exceeds_upstream"
    past = give(owner, cred, people.carol, expires_at=(timezone.now() - timedelta(minutes=1)).isoformat())
    assert past.json()["error"]["code"] == "invalid_expiry"


def test_archived_credentials_cannot_be_shared_and_disappear_for_grantees(client_for, people, cred):
    owner = client_for(people.owner)
    give(owner, cred, people.bob)
    owner.delete(f"/api/v1/vault/credentials/{cred}/")
    assert client_for(people.bob).get("/api/v1/vault/credentials/").json()["count"] == 0
    assert reveal(client_for(people.bob), cred).status_code == 404
    owner.post(f"/api/v1/vault/credentials/{cred}/restore/")
    assert reveal(client_for(people.bob), cred).status_code == 200


def test_share_is_audited_and_notified_without_secrets(client_for, people, cred):
    share_id = give(client_for(people.owner), cred, people.bob, "VIEW", is_view_once=False).json()["id"]
    entry = AuditLog.objects.get(action=AuditAction.SHARE, outcome=AuditOutcome.SUCCESS)
    assert entry.metadata["share_id"] == share_id and entry.metadata["grantee_id"] == str(people.bob.id)
    note = Notification.objects.get(recipient=people.bob, type="SHARE_CREATED")
    assert "Prod DB" in note.title
    assert STRONG_SECRET not in " ".join(str(r) for r in AuditLog.objects.values_list())
    assert STRONG_SECRET not in " ".join(str(r) for r in Notification.objects.values_list())


# --------------------------------------------------------------------------- cascading revocation


def chain_of_three(client_for, people, cred):
    """owner -> bob (SHARE) -> carol (SHARE) -> dave (VIEW)"""
    root = give(client_for(people.owner), cred, people.bob, "SHARE").json()["id"]
    middle = give(client_for(people.bob), cred, people.carol, "SHARE").json()["id"]
    leaf = give(client_for(people.carol), cred, people.dave, "VIEW").json()["id"]
    return root, middle, leaf


def test_revoking_a_parent_invalidates_every_descendant(client_for, people, cred):
    root, middle, leaf = chain_of_three(client_for, people, cred)
    for user in (people.bob, people.carol, people.dave):
        assert reveal(client_for(user), cred).status_code == 200

    response = client_for(people.owner).post(f"/api/v1/shares/{root}/revoke/")
    assert response.json() == {"revoked": 3}

    for user in (people.bob, people.carol, people.dave):
        assert reveal(client_for(user), cred).status_code == 404  # no usable grant: not even visible
    rows = {str(s.pk): s for s in Share.objects.all()}
    assert all(s.revoked_at is not None for s in rows.values())
    assert rows[root].revoke_reason == "revoked"
    assert rows[middle].revoke_reason == rows[leaf].revoke_reason == "cascade"
    entry = AuditLog.objects.get(action=AuditAction.REVOKE, outcome=AuditOutcome.SUCCESS)
    assert entry.metadata == {"share_id": root, "revoked_grants": 3, "cascade": 2}
    notified = set(Notification.objects.filter(type="SHARE_REVOKED").values_list("recipient_id", flat=True))
    assert notified == {people.bob.id, people.carol.id, people.dave.id}


def test_revocation_only_affects_the_revoked_subtree(client_for, people, cred, make_user):
    erin = make_user(full_name="Erin")
    give(client_for(people.owner), cred, people.bob, "SHARE")
    to_carol = give(client_for(people.bob), cred, people.carol, "SHARE").json()["id"]
    give(client_for(people.carol), cred, people.dave, "VIEW")
    give(client_for(people.bob), cred, erin, "VIEW")  # sibling branch

    assert client_for(people.bob).post(f"/api/v1/shares/{to_carol}/revoke/").json() == {"revoked": 2}
    assert reveal(client_for(people.bob), cred).status_code == 200
    assert reveal(client_for(erin), cred).status_code == 200
    assert reveal(client_for(people.carol), cred).status_code == 404
    assert reveal(client_for(people.dave), cred).status_code == 404


def test_who_may_revoke(client_for, people, cred, sec_admin, make_user):
    root, middle, leaf = chain_of_three(client_for, people, cred)
    stranger = make_user(full_name="Stranger")

    denied = client_for(people.dave).post(f"/api/v1/shares/{middle}/revoke/")  # a descendant may not revoke upward
    assert denied.status_code == 403
    assert AuditLog.objects.filter(action=AuditAction.REVOKE, outcome=AuditOutcome.DENIED).count() == 1
    assert client_for(stranger).post(f"/api/v1/shares/{leaf}/revoke/").status_code == 403

    assert client_for(people.bob).post(f"/api/v1/shares/{leaf}/revoke/").json() == {"revoked": 1}  # ancestor holder
    assert client_for(people.bob).post(f"/api/v1/shares/{leaf}/revoke/").json() == {"revoked": 0}  # idempotent

    admin_client = client_for(sec_admin)
    assert admin_client.post(f"/api/v1/shares/{root}/revoke/").json() == {"revoked": 2}  # incident response
    assert reveal(admin_client, cred).status_code == 404  # ...without gaining access to the secret


def test_ancestor_chain_is_checked_even_if_a_descendant_row_was_missed(client_for, people, cred):
    """Defense in depth: even if the cascade had not touched a child row, a revoked ancestor blocks it."""
    root = give(client_for(people.owner), cred, people.bob, "SHARE").json()["id"]
    give(client_for(people.bob), cred, people.carol, "VIEW")
    Share.objects.filter(pk=root).update(revoked_at=timezone.now())  # bypasses the cascade on purpose

    response = reveal(client_for(people.carol), cred)
    assert response.status_code == 403
    assert STRONG_SECRET not in response.content.decode()


def test_expired_grants_and_children_of_expired_grants_are_unusable(client_for, people, cred):
    root = give(client_for(people.owner), cred, people.bob, "SHARE").json()["id"]
    child = give(client_for(people.bob), cred, people.carol, "VIEW").json()["id"]

    Share.objects.filter(pk=root).update(expires_at=timezone.now() - timedelta(seconds=1))
    Share.objects.filter(pk=child).update(expires_at=timezone.now() + timedelta(days=3))  # child outliving parent
    assert reveal(client_for(people.bob), cred).status_code == 404
    assert reveal(client_for(people.carol), cred).status_code == 403


def test_suspension_pauses_delegated_access_and_reactivation_restores_it(client_for, admin, people, cred):
    give(client_for(people.owner), cred, people.bob, "SHARE")
    give(client_for(people.bob), cred, people.carol, "VIEW")
    admin_client = client_for(admin)

    admin_client.patch(f"/api/v1/users/{people.bob.id}/", {"status": "SUSPENDED"}, format="json")
    assert reveal(client_for(people.carol), cred).status_code == 403
    admin_client.patch(f"/api/v1/users/{people.bob.id}/", {"status": "ACTIVE"}, format="json")
    assert reveal(client_for(people.carol), cred).status_code == 200


def test_deactivation_revokes_received_grants_but_keeps_grants_given_as_owner(client_for, admin, people, cred):
    give(client_for(people.owner), cred, people.bob, "SHARE")
    give(client_for(people.bob), cred, people.carol, "VIEW")
    bobs_own = create_credential(client_for(people.bob), title="Bob's DB").json()["id"]
    give(client_for(people.bob), bobs_own, people.carol, "VIEW")

    client_for(admin).patch(f"/api/v1/users/{people.bob.id}/", {"status": "DEACTIVATED"}, format="json")
    assert reveal(client_for(people.carol), cred).status_code == 404  # came through Bob: revoked
    assert reveal(client_for(people.carol), bobs_own).status_code == 200  # Bob owned it: team keeps access
    assert set(Share.objects.filter(credential_id=cred).values_list("revoke_reason", flat=True)) == {
        "account_deactivated",
        "cascade",
    }


# --------------------------------------------------------------------------- view-once


def test_view_once_is_consumed_by_the_first_reveal_and_then_gone(client_for, people, cred):
    share_id = give(client_for(people.owner), cred, people.bob, "VIEW", is_view_once=True).json()["id"]
    bob = client_for(people.bob)
    assert reveal(bob, cred).json() == {"password": STRONG_SECRET}

    for purpose in ("view", "copy"):
        gone = reveal(bob, cred, purpose)
        assert gone.status_code == 410 and gone.json()["error"]["code"] == "view_once_consumed"
    listed = bob.get(f"/api/v1/vault/credentials/{cred}/").json()
    assert listed["sharing"]["consumed"] is True and listed["permissions"] == []
    assert Share.objects.get(pk=share_id).burned_at is not None
    entry = AuditLog.objects.get(action=AuditAction.REVEAL, outcome=AuditOutcome.SUCCESS)
    assert entry.metadata == {"purpose": "view", "share_id": share_id, "view_once": True}
    assert reveal(client_for(people.owner), cred).status_code == 200  # the owner is unaffected


def test_view_once_must_be_view_only_and_allowed_by_policy(client_for, people, cred):
    owner = client_for(people.owner)
    assert give(owner, cred, people.bob, "EDIT", is_view_once=True).json()["error"]["code"] == "invalid_permission"
    policy = policy_for(people.owner.organization)
    policy.allow_view_once = False
    policy.save()
    assert give(owner, cred, people.bob, "VIEW", is_view_once=True).json()["error"]["code"] == "view_once_disabled"


def test_failed_authorization_does_not_consume_a_view_once_grant(client_for, people, cred, monkeypatch):
    from rest_framework.exceptions import PermissionDenied

    share_id = give(client_for(people.owner), cred, people.bob, "VIEW", is_view_once=True).json()["id"]

    def deny(ctx):
        raise PermissionDenied("blocked (e.g. untrusted device or lockdown)", code="blocked")

    monkeypatch.setattr("core.access_gate._sensitive_checks", [deny])
    assert reveal(client_for(people.bob), cred).status_code == 403
    assert Share.objects.get(pk=share_id).burned_at is None

    monkeypatch.setattr("core.access_gate._sensitive_checks", [])
    assert reveal(client_for(people.bob), cred).status_code == 200


def test_a_failed_audit_write_rolls_back_the_view_once_burn(client_for, people, cred):
    share_id = give(client_for(people.owner), cred, people.bob, "VIEW", is_view_once=True).json()["id"]
    with mock.patch("apps.audit.services._append", side_effect=RuntimeError("audit down")):
        assert reveal(client_for(people.bob), cred).status_code == 500
    assert Share.objects.get(pk=share_id).burned_at is None
    assert reveal(client_for(people.bob), cred).status_code == 200


# --------------------------------------------------------------------------- listing and trees


def test_share_lists_by_direction_and_state(client_for, people, cred):
    root, middle, leaf = chain_of_three(client_for, people, cred)
    owner = client_for(people.owner)
    assert [s["id"] for s in owner.get("/api/v1/shares/", {"direction": "given"}).json()["results"]] == [root]
    bob_received = client_for(people.bob).get("/api/v1/shares/", {"direction": "received"}).json()["results"]
    assert [s["id"] for s in bob_received] == [root]
    owner.post(f"/api/v1/shares/{root}/revoke/")
    assert (
        owner.get("/api/v1/shares/", {"state": "revoked"}).json()["count"] == 3
    )  # owner sees grants on own credential
    assert owner.get("/api/v1/shares/", {"state": "active"}).json()["count"] == 0


def test_delegation_tree_visibility(client_for, people, cred, sec_admin, make_user):
    root, middle, leaf = chain_of_three(client_for, people, cred)
    url = f"/api/v1/shares/tree/{cred}/"

    full = client_for(people.owner).get(url).json()
    assert {n["id"] for n in full["nodes"]} == {root, middle, leaf}
    assert {n["id"]: n["parent_share"] for n in full["nodes"]} == {root: None, middle: root, leaf: middle}
    assert "password" not in str(full) and STRONG_SECRET not in str(full)

    assert {n["id"] for n in client_for(people.carol).get(url).json()["nodes"]} == {middle, leaf}
    assert {n["id"] for n in client_for(sec_admin).get(url).json()["nodes"]} == {root, middle, leaf}
    assert client_for(make_user()).get(url).status_code == 404
    assert client_for(people.owner).get("/api/v1/shares/tree/not-a-uuid/").status_code == 404


def test_people_directory_lists_active_colleagues_only(client_for, people, make_user, other_admin):
    make_user(full_name="Gone", status="DEACTIVATED")
    names = {
        p["full_name"] for p in client_for(people.owner).get("/api/v1/people/", {"page_size": 100}).json()["results"]
    }
    assert {"Bob", "Carol", "Dave"} <= names
    assert people.owner.full_name not in names and "Gone" not in names and other_admin.full_name not in names
