"""Credential-level access lock: a transaction-scoped PostgreSQL advisory lock.

Readers (reveal, edit through a grant) take it SHARED; grant mutations (create, revoke) take it EXCLUSIVE.

Why not row locks: with SELECT ... FOR SHARE, PostgreSQL keeps granting new share locks while a FOR UPDATE
request waits, so a steady stream of reveals can starve a revocation indefinitely (our concurrency test
measured a 23-second delay). The heavyweight lock manager used by advisory locks queues new shared requests
behind a waiting exclusive one, so a revocation waits only for reveals already in flight.

Lock order everywhere: this advisory lock first, then any row locks. That ordering prevents deadlocks.
"""

from django.db import connection

_NAMESPACE = 0x5EC7  # identifies SecureVault credential-access locks among other advisory locks


def lock_credential_access(credential_id, *, exclusive: bool) -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("Credential access locks are transaction-scoped; call inside transaction.atomic().")
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    with connection.cursor() as cursor:
        # hashtext() maps the UUID onto the 32-bit key space; a collision only adds harmless serialisation.
        cursor.execute(f"SELECT {function}(%s, hashtext(%s))", [_NAMESPACE, str(credential_id)])
