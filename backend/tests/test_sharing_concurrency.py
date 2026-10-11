"""Concurrency tests against real PostgreSQL: threads with separate connections, released together by a barrier.

These run with transaction=True (no wrapping test transaction), so each thread commits for real.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts.models import User
from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.organizations.models import Organization
from apps.sharing import services as sharing
from apps.sharing.models import Share
from apps.vault import services as vault
from apps.vault.models import Credential

from .vault_helpers import STRONG_SECRET

pytestmark = pytest.mark.django_db(transaction=True)
WORKERS = 12


@pytest.fixture
def world(isolated_cache):
    org = Organization.objects.create(name="Concurrency Ltd", slug="concurrency")

    def user(name):
        return User.objects.create_user(
            f"{name}@c.test", org, "Sturdy-Test-Passphrase-42", full_name=name, status="ACTIVE"
        )

    owner, bob, carol = user("owner"), user("bob"), user("carol")
    credential = vault.create_credential(user=owner, title="Shared DB", password=STRONG_SECRET)
    return owner, bob, carol, credential


def run_in_threads(n, fn):
    barrier = threading.Barrier(n)

    def worker(i):
        try:
            barrier.wait()
            return fn(i)
        finally:
            connection.close()  # each thread opened its own connection

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def attempt_reveal(user_id, credential_id):
    user = User.objects.select_related("organization").get(pk=user_id)
    credential = Credential.objects.select_related("organization").get(pk=credential_id)
    try:
        return ("ok", vault.reveal(user=user, item=credential, purpose="view"))
    except APIException as exc:
        return (exc.status_code, getattr(exc, "error_code", None) or exc.get_codes())


def test_concurrent_view_once_reveals_allow_exactly_one_success(world):
    owner, bob, _, credential = world
    share = sharing.create_share(actor=owner, credential=credential, grantee=bob, permission="VIEW", is_view_once=True)

    results = run_in_threads(WORKERS, lambda i: attempt_reveal(bob.pk, credential.pk))

    successes = [r for r in results if r[0] == "ok"]
    assert len(successes) == 1, results
    assert successes[0][1] == STRONG_SECRET
    assert all(r == (410, "view_once_consumed") for r in results if r[0] != "ok"), results
    assert Share.objects.get(pk=share.pk).burned_at is not None
    assert AuditLog.objects.filter(action=AuditAction.REVEAL, outcome=AuditOutcome.SUCCESS).count() == 1


def test_no_reveal_succeeds_after_a_revocation_commits(world):
    """Reveal loops race a revocation. Every successful reveal must have committed before the revocation did,
    and the revocation must not be starved by the stream of reveals (regression: row-level FOR SHARE locks
    delayed it by ~23 s)."""
    owner, bob, _, credential = world
    share = sharing.create_share(actor=owner, credential=credential, grantee=bob, permission="VIEW")
    denied_after = []

    def reveal_until_denied(i):
        successes = 0
        for _ in range(2000):
            outcome = attempt_reveal(bob.pk, credential.pk)
            if outcome[0] != "ok":
                denied_after.append(outcome)
                return successes
            successes += 1
        return successes

    def revoke_soon(i):
        if i == 0:
            time.sleep(0.15)
            owner_fresh = User.objects.select_related("organization").get(pk=owner.pk)
            started = time.monotonic()
            sharing.revoke_share(actor=owner_fresh, share=Share.objects.select_related("credential").get(pk=share.pk))
            return ("revoked", time.monotonic() - started)
        return reveal_until_denied(i)

    results = run_in_threads(6, revoke_soon)
    revoke_seconds = next(r[1] for r in results if isinstance(r, tuple))
    assert revoke_seconds < 3.0, f"revocation waited {revoke_seconds:.1f}s behind the reveal stream"
    assert sum(r for r in results if isinstance(r, int)) > 0  # reveals really were happening before the revoke

    revoked_at = Share.objects.get(pk=share.pk).revoked_at
    last_success = (
        AuditLog.objects.filter(action=AuditAction.REVEAL, outcome=AuditOutcome.SUCCESS, actor_id=bob.pk)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    assert last_success < revoked_at
    assert len(denied_after) == 5  # every reveal loop eventually saw the revocation and stopped
    assert all(outcome[0] == 403 for outcome in denied_after), denied_after


def test_a_child_grant_cannot_survive_a_concurrent_parent_revocation(world):
    """Bob keeps delegating to Carol while the owner revokes Bob. Afterwards Carol must hold no usable grant."""
    owner, bob, carol, credential = world
    root = sharing.create_share(actor=owner, credential=credential, grantee=bob, permission="SHARE")

    def delegate_or_revoke(i):
        if i == 0:
            time.sleep(0.05)
            sharing.revoke_share(
                actor=User.objects.select_related("organization").get(pk=owner.pk),
                share=Share.objects.select_related("credential").get(pk=root.pk),
            )
            return "revoked"
        bob_fresh = User.objects.select_related("organization").get(pk=bob.pk)
        outcomes = []
        for _ in range(40):
            try:
                cred = Credential.objects.select_related("organization").get(pk=credential.pk)
                sharing.create_share(
                    actor=bob_fresh,
                    credential=cred,
                    grantee=carol,
                    permission="VIEW",
                    expires_at=timezone.now() + timedelta(hours=1),
                )
                outcomes.append("created")
            except APIException as exc:
                outcomes.append(exc.status_code)
        return outcomes

    run_in_threads(4, delegate_or_revoke)

    live_for_carol = [
        s
        for s in Share.objects.filter(credential=credential, grantee=carol)
        if s.revoked_at is None and s.burned_at is None
    ]
    assert live_for_carol == []
    assert attempt_reveal(carol.pk, credential.pk)[0] in (403, 404)
