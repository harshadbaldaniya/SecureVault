"""Share grants: create (bounded by the upstream grant), revoke (cascading, atomic), expiry processing.

Concurrency rule: every grant mutation for a credential takes that credential's access lock EXCLUSIVELY
(apps.sharing.locks), then the row FOR UPDATE. Reveals and grant-based edits hold the same access lock SHARED
for their whole transaction, so a revocation waits only for reveals already in flight, cannot be starved by new
ones, and every reveal that starts afterwards sees it. Result: once a revocation has committed, no grant in
the revoked subtree can be used.
"""

from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone
from rest_framework import exceptions

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditOutcome
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.policies.models import policy_for
from apps.vault.models import Credential
from core.access_gate import Action, authorize
from core.exceptions import ServiceError
from core.permissions import Perm, has_perm

from .access import RANK, chain_is_live, share_access
from .locks import lock_credential_access
from .models import MAX_DELEGATION_DEPTH, Share

EXPIRING_SOON = timedelta(hours=24)


def _lock_credential(credential_id) -> Credential:
    lock_credential_access(credential_id, exclusive=True)
    return Credential.objects.select_for_update().select_related("organization").get(pk=credential_id)


def create_share(
    *, actor: User, credential: Credential, grantee: User, permission: str, expires_at=None, is_view_once: bool = False
) -> Share:
    authorize(actor, credential, Action.SHARE)  # owner or SHARE-holder; runs every zero-trust check

    if grantee.organization_id != actor.organization_id or grantee.status != User.Status.ACTIVE:
        raise ServiceError("You can only share with active members of your organization.", "invalid_grantee")
    if grantee.pk == actor.pk:
        raise ServiceError("You cannot share with yourself.", "invalid_grantee")
    if grantee.pk == credential.owner_id:
        raise ServiceError("The owner already has full access.", "invalid_grantee")

    policy = policy_for(actor.organization)
    if is_view_once:
        if not policy.allow_view_once:
            raise ServiceError("Your organization's policy does not allow view-once shares.", "view_once_disabled")
        if permission != Share.Permission.VIEW:
            raise ServiceError("View-once shares can only grant VIEW.", "invalid_permission")

    with transaction.atomic():
        locked = _lock_credential(credential.pk)
        now = timezone.now()  # after the lock: decisions use the time at which we actually hold it
        if locked.is_archived:
            raise ServiceError("Archived credentials cannot be shared.", "archived", status_code=409)

        policy_limit = now + timedelta(days=policy.max_share_duration_days)
        if locked.owner_id == actor.pk:
            parent, depth, max_rank, max_expiry = None, 0, RANK[Share.Permission.SHARE], policy_limit
        else:
            access = share_access(actor, locked, now=now)  # re-evaluated under the lock
            parent = access.share
            if parent is None or parent.permission != Share.Permission.SHARE or not chain_is_live(parent, now):
                raise exceptions.PermissionDenied("You do not have permission to do this.", code="permission_denied")
            depth = parent.depth + 1
            if depth > MAX_DELEGATION_DEPTH:
                raise ServiceError(f"Delegation chains are limited to {MAX_DELEGATION_DEPTH} levels.", "too_deep")
            max_rank, max_expiry = RANK[parent.permission], min(parent.expires_at, policy_limit)

        if RANK[permission] > max_rank:
            raise ServiceError("You cannot grant more access than you have.", "exceeds_upstream")
        expires_at = expires_at or max_expiry
        if expires_at <= now:
            raise ServiceError("The expiry must be in the future.", "invalid_expiry")
        if expires_at > max_expiry:
            raise ServiceError(
                "The expiry cannot be later than your own access or the policy limit "
                f"({max_expiry:%Y-%m-%d %H:%M} UTC).",
                "exceeds_upstream",
            )

        open_grant = (
            Share.objects.select_for_update()
            .filter(credential=locked, grantor=actor, grantee=grantee, revoked_at__isnull=True, burned_at__isnull=True)
            .first()
        )
        if open_grant is not None:
            if open_grant.expires_at > now:
                raise ServiceError(
                    "You already share this credential with that person. Revoke it first.",
                    "already_shared",
                    status_code=409,
                )
            _revoke_subtree(open_grant, actor, "superseded", now)  # expired grant: clear it so a new one can exist

        share = Share.objects.create(
            organization=locked.organization,
            credential=locked,
            grantor=actor,
            grantee=grantee,
            parent_share=parent,
            depth=depth,
            permission=permission,
            expires_at=expires_at,
            is_view_once=is_view_once,
        )
        audit.record(
            AuditAction.SHARE,
            actor=actor,
            target=locked,
            target_type="credential",
            metadata={
                "share_id": str(share.pk),
                "grantee_id": str(grantee.pk),
                "permission": permission,
                "expires_at": expires_at.isoformat(),
                "view_once": is_view_once,
                "parent_share_id": str(parent.pk) if parent else None,
                "depth": depth,
            },
        )
        view_once_note = " (view once)" if is_view_once else ""
        notify(
            [grantee],
            Notification.Type.SHARE_CREATED,
            f'{actor.full_name} shared "{locked.title}" with you',
            f"Access: {permission.lower()}{view_once_note}, until {expires_at:%Y-%m-%d %H:%M} UTC.",
            link="/vault",
        )
    return share


def _revoke_subtree(share: Share, actor: User | None, reason: str, now) -> list[tuple]:
    """Revoke `share` and every descendant in ONE statement. Returns [(share_id, grantee_id), ...] revoked."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH RECURSIVE subtree AS (
                SELECT id FROM sharing_share WHERE id = %s
                UNION ALL
                SELECT child.id FROM sharing_share child JOIN subtree ON child.parent_share_id = subtree.id
            )
            UPDATE sharing_share
               SET revoked_at = %s,
                   revoked_by_id = %s,
                   revoke_reason = CASE WHEN id = %s THEN %s ELSE 'cascade' END,
                   updated_at = %s
             WHERE id IN (SELECT id FROM subtree) AND revoked_at IS NULL
         RETURNING id, grantee_id
            """,
            [share.pk, now, actor.pk if actor else None, share.pk, reason, now],
        )
        return cursor.fetchall()


def can_revoke(actor: User, share: Share) -> bool:
    """Owner, the grantor, anyone holding an ancestor grant, or an administrator during an incident."""
    if actor.organization_id != share.organization_id:
        return False
    if actor.pk in (share.credential.owner_id, share.grantor_id):
        return True
    if has_perm(actor, Perm.SHARES_REVOKE_ANY):
        return True
    node = share.parent_share
    while node is not None:
        if node.grantee_id == actor.pk:
            return True
        node = node.parent_share
    return False


def revoke_share(*, actor: User, share: Share, reason: str = "revoked") -> int:
    """Revoke a grant and its whole delegation subtree atomically. Returns the number of grants revoked."""
    if not can_revoke(actor, share):
        audit.record(
            AuditAction.REVOKE,
            actor=actor,
            outcome=AuditOutcome.DENIED,
            target_type="share",
            target_id=str(share.pk),
            reason="permission_denied",
            fail_silently=True,
        )
        raise exceptions.PermissionDenied("You do not have permission to revoke this share.", code="permission_denied")

    with transaction.atomic():
        credential = _lock_credential(share.credential_id)
        now = timezone.now()  # timestamp the revocation when it actually takes effect, not before the lock wait
        current = Share.objects.select_for_update().get(pk=share.pk)
        if current.revoked_at is not None:
            return 0  # idempotent
        revoked = _revoke_subtree(current, actor, reason, now)
        audit.record(
            AuditAction.REVOKE,
            actor=actor,
            target=credential,
            target_type="credential",
            metadata={"share_id": str(current.pk), "revoked_grants": len(revoked), "cascade": len(revoked) - 1},
        )
        affected = User.objects.filter(pk__in={grantee for _, grantee in revoked})
        notify(
            affected,
            Notification.Type.SHARE_REVOKED,
            f'Your access to "{credential.title}" was revoked',
            "Ask the owner if you still need it.",
            priority=Notification.Priority.HIGH,
            link="/vault",
        )
    return len(revoked)


def revoke_received_grants(*, actor: User | None, user: User, reason: str) -> int:
    """Revoke every open grant `user` received, with everything they delegated from it.

    Used when an account is deactivated (the person has left). Grants the user gave as an OWNER are kept,
    so their team keeps access to credentials the departing person owned.
    Must run inside the caller's transaction.
    """
    total = 0
    for share_id, credential_id in Share.objects.filter(grantee=user, revoked_at__isnull=True).values_list(
        "pk", "credential_id"
    ):
        _lock_credential(credential_id)
        current = Share.objects.select_for_update().get(pk=share_id)
        if current.revoked_at is None:
            total += len(_revoke_subtree(current, actor, reason, timezone.now()))
    return total


def process_expiry(*, now=None) -> dict:
    """Send 'expiring soon' and 'expired' notifications once per grant. Expired grants are already unusable;
    this only informs people (the access check enforces expiry on every request)."""
    now = now or timezone.now()
    soon = Share.objects.filter(
        revoked_at__isnull=True,
        burned_at__isnull=True,
        expiring_notified_at__isnull=True,
        expires_at__gt=now,
        expires_at__lte=now + EXPIRING_SOON,
    ).select_related("credential", "grantee")
    expired = Share.objects.filter(
        revoked_at__isnull=True, burned_at__isnull=True, expired_notified_at__isnull=True, expires_at__lte=now
    ).select_related("credential", "grantee", "grantor")
    counts = {"expiring": 0, "expired": 0}
    for share in soon:
        with transaction.atomic():
            notify(
                [share.grantee],
                Notification.Type.SHARE_EXPIRING,
                f'Your access to "{share.credential.title}" expires soon',
                f"Expires {share.expires_at:%Y-%m-%d %H:%M} UTC.",
                link="/vault",
            )
            Share.objects.filter(pk=share.pk).update(expiring_notified_at=now)
        counts["expiring"] += 1
    for share in expired:
        with transaction.atomic():
            notify(
                [share.grantee, share.grantor],
                Notification.Type.SHARE_EXPIRED,
                f'Access to "{share.credential.title}" has expired',
                link="/vault",
            )
            Share.objects.filter(pk=share.pk).update(expired_notified_at=now)
        counts["expired"] += 1
    return counts
