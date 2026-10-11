"""The credential list resolves a whole page of grants at once (prefetch_share_access). It must reach exactly the
decisions the per-credential path (used by detail views and by every reveal) reaches, in every grant state."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.sharing import services as sharing
from apps.sharing.access import chain_is_live, prefetch_share_access, share_access
from apps.sharing.models import Share
from apps.vault.models import Credential

from .vault_helpers import CREDENTIALS, create_credential

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario(client_for, make_user):
    """One credential per grant state, all visible to `reader`."""
    owner, reader = make_user(full_name="Olga Owner"), make_user(full_name="Rita Reader")
    delegate, suspended_delegate = make_user(full_name="Dan Delegate"), make_user(full_name="Sue Suspended")
    owner_client = client_for(owner)
    now = timezone.now()
    credentials: dict[str, Credential] = {}

    def credential(name):
        created = create_credential(owner_client, title=name).json()["id"]
        credentials[name] = Credential.objects.get(pk=created)
        return credentials[name]

    def grant(name, grantor, grantee, permission, **extra):
        return sharing.create_share(
            actor=grantor, credential=credentials[name], grantee=grantee, permission=permission, **extra
        )

    credential("direct edit")
    grant("direct edit", owner, reader, "EDIT")

    credential("view once, used")
    used = grant("view once, used", owner, reader, "VIEW", is_view_once=True)
    Share.objects.filter(pk=used.pk).update(burned_at=now)

    credential("live chain")
    grant("live chain", owner, delegate, "SHARE")
    grant("live chain", delegate, reader, "VIEW")

    credential("parent expired")
    parent = grant("parent expired", owner, delegate, "SHARE")
    grant("parent expired", delegate, reader, "VIEW")
    Share.objects.filter(pk=parent.pk).update(expires_at=now - timedelta(hours=1))

    credential("delegate suspended")
    grant("delegate suspended", owner, suspended_delegate, "SHARE")
    grant("delegate suspended", suspended_delegate, reader, "EDIT")
    User.objects.filter(pk=suspended_delegate.pk).update(status=User.Status.SUSPENDED)

    credential("best of two grants")
    grant("best of two grants", owner, reader, "VIEW")
    grant("best of two grants", owner, delegate, "SHARE")
    grant("best of two grants", delegate, reader, "SHARE")

    credential("deep chain")
    people = [owner] + [make_user(full_name=f"Level {i}") for i in range(1, 4)] + [reader]
    for grantor, grantee in zip(people, people[1:], strict=False):
        grant("deep chain", grantor, grantee, "SHARE")

    credential("not shared with reader")
    return {"owner": owner, "reader": reader, "credentials": credentials}


def summary(item):
    return {key: item[key] for key in ("access", "permissions", "sharing")} | {"title": item["title"]}


def test_list_decisions_equal_detail_decisions_in_every_grant_state(client_for, scenario):
    client = client_for(scenario["reader"])
    listed = {item["title"]: item for item in client.get(CREDENTIALS, {"scope": "shared"}).json()["results"]}

    # Sanity: the scenario really produced different outcomes, so the comparison below means something.
    assert listed["direct edit"]["permissions"] == ["COPY", "EDIT", "REVEAL", "VIEW"]
    assert listed["view once, used"]["permissions"] == [] and listed["view once, used"]["sharing"]["consumed"]
    assert listed["live chain"]["permissions"] == ["COPY", "REVEAL", "VIEW"]
    assert listed["parent expired"]["permissions"] == []  # visible in the list, but nothing may be done
    assert listed["delegate suspended"]["permissions"] == []
    assert "SHARE" in listed["best of two grants"]["permissions"]  # the strongest live grant wins
    assert "SHARE" in listed["deep chain"]["permissions"]
    assert "not shared with reader" not in listed

    for title, item in listed.items():
        detail = client.get(f"{CREDENTIALS}{item['id']}/").json()
        assert summary(detail) == summary(item), title


def test_prefetch_resolves_the_same_access_as_share_access(scenario):
    reader = scenario["reader"]
    credentials = [c for c in scenario["credentials"].values()]
    expected = {c.pk: share_access(reader, Credential.objects.get(pk=c.pk)) for c in credentials}

    fresh = [Credential.objects.get(pk=c.pk) for c in credentials]
    prefetch_share_access(reader, fresh)
    for credential in fresh:
        got = credential.access_for(reader)
        want = expected[credential.pk]
        assert (got.share.pk if got.share else None) == (want.share.pk if want.share else None), credential.title
        assert got.consumed == want.consumed, credential.title


def test_chain_is_live_gives_the_same_answer_with_or_without_preloaded_ancestors(scenario):
    reader = scenario["reader"]
    for share in Share.objects.filter(grantee=reader, revoked_at__isnull=True).select_related("grantor"):
        ancestors = {s.pk: s for s in Share.objects.filter(credential=share.credential).select_related("grantee")}
        assert chain_is_live(share, ancestors=ancestors) == chain_is_live(share), share.credential.title
