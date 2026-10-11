"""Evaluate what a non-owner may do with a credential through share grants.

This is step "share validity and expiry" of the zero-trust pipeline; it is called from
Credential.permissions_for(), which core.access_gate.authorize() consults.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from django.utils import timezone

from core.access_gate import Action

from .models import MAX_DELEGATION_DEPTH, Share

RANK = {Share.Permission.VIEW: 1, Share.Permission.EDIT: 2, Share.Permission.SHARE: 3}

_VIEW = frozenset({Action.VIEW, Action.REVEAL, Action.COPY})
ACTIONS = {
    Share.Permission.VIEW: _VIEW,
    Share.Permission.EDIT: _VIEW | {Action.EDIT},
    Share.Permission.SHARE: _VIEW | {Action.EDIT, Action.SHARE},
}


@dataclass(frozen=True)
class ShareAccess:
    share: Share | None  # the best currently usable grant, if any
    consumed: bool  # the user's only remaining grant is a used view-once grant

    @property
    def actions(self) -> frozenset:
        return ACTIONS[self.share.permission] if self.share else frozenset()


def _live(share: Share, now) -> bool:
    return share.revoked_at is None and share.burned_at is None and share.expires_at > now


def _parent(node: Share, ancestors: Mapping | None) -> Share:
    """The grant `node` was delegated from: from the preloaded `ancestors` when given, else from the database."""
    if ancestors is not None and node.parent_share_id in ancestors:
        return ancestors[node.parent_share_id]
    return (
        Share.objects.select_related("grantee")
        .only("id", "parent_share_id", "revoked_at", "burned_at", "expires_at", "grantee__status")
        .get(pk=node.parent_share_id)
    )


def chain_is_live(share: Share, now=None, ancestors: Mapping | None = None) -> bool:
    """True only if the grant and every ancestor up to the owner's root grant are live, and every intermediate
    grantee is still an ACTIVE account (suspending someone pauses everything delegated through them)."""
    now = now or timezone.now()
    node = share
    for _ in range(MAX_DELEGATION_DEPTH + 2):
        if not _live(node, now):
            return False
        if node.parent_share_id is None:
            return True
        node = _parent(node, ancestors)
        if node.grantee.status != "ACTIVE":
            return False
    return False  # deeper than allowed: treat as invalid


def share_access(
    user, credential, *, now=None, shares: Sequence[Share] | None = None, ancestors: Mapping | None = None
) -> ShareAccess:
    """What `user` may do with `credential` through grants. `shares`/`ancestors` let a list view pass in rows it
    loaded for a whole page; the decision logic is the same either way."""
    now = now or timezone.now()
    best: Share | None = None
    consumed = False
    if shares is None:
        shares = Share.objects.filter(
            credential_id=credential.pk, grantee_id=user.pk, revoked_at__isnull=True
        ).select_related("grantor")
    for share in shares:
        if share.burned_at is not None:
            consumed = True
            continue
        if share.expires_at <= now or not chain_is_live(share, now, ancestors):
            continue
        key = (RANK[share.permission], not share.is_view_once, share.expires_at)
        if best is None or key > (RANK[best.permission], not best.is_view_once, best.expires_at):
            best = share
    return ShareAccess(share=best, consumed=consumed and best is None)


def prefetch_share_access(user, credentials: Sequence, *, now=None) -> None:
    """Resolve `user`'s access to every credential in a page with a constant number of queries.

    One query for the viewer's grants on the page, then one per level of delegation above them (at most
    MAX_DELEGATION_DEPTH, and usually none), instead of a few queries per credential. Results are stored on each
    instance, where Credential.access_for() finds them, so the serializer needs no further queries.
    """
    now = now or timezone.now()
    others = [credential for credential in credentials if credential.owner_id != user.pk]
    if not others:
        return
    grants = defaultdict(list)
    for share in Share.objects.filter(
        credential_id__in=[credential.pk for credential in others], grantee_id=user.pk, revoked_at__isnull=True
    ).select_related("grantor"):
        grants[share.credential_id].append(share)

    ancestors: dict = {}
    frontier = {share.parent_share_id for shares in grants.values() for share in shares if share.parent_share_id}
    for _ in range(MAX_DELEGATION_DEPTH + 1):
        frontier -= ancestors.keys()
        if not frontier:
            break
        fetched = list(Share.objects.filter(pk__in=frontier).select_related("grantee"))
        ancestors.update({node.pk: node for node in fetched})
        frontier = {node.parent_share_id for node in fetched if node.parent_share_id}

    for credential in others:
        access = share_access(user, credential, now=now, shares=grants.get(credential.pk, []), ancestors=ancestors)
        credential.__dict__.setdefault("_access_cache", {})[user.id] = access
