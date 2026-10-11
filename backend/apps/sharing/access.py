"""Evaluate what a non-owner may do with a credential through share grants.

This is step "share validity and expiry" of the zero-trust pipeline; it is called from
Credential.permissions_for(), which core.access_gate.authorize() consults.
"""

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


def chain_is_live(share: Share, now=None) -> bool:
    """True only if the grant and every ancestor up to the owner's root grant are live, and every intermediate
    grantee is still an ACTIVE account (suspending someone pauses everything delegated through them)."""
    now = now or timezone.now()
    node = share
    for _ in range(MAX_DELEGATION_DEPTH + 2):
        if not _live(node, now):
            return False
        if node.parent_share_id is None:
            return True
        node = (
            Share.objects.select_related("grantee")
            .only("id", "parent_share_id", "revoked_at", "burned_at", "expires_at", "grantee__status")
            .get(pk=node.parent_share_id)
        )
        if node.grantee.status != "ACTIVE":
            return False
    return False  # deeper than allowed: treat as invalid


def share_access(user, credential, *, now=None) -> ShareAccess:
    now = now or timezone.now()
    best: Share | None = None
    consumed = False
    for share in Share.objects.filter(credential_id=credential.pk, grantee_id=user.pk, revoked_at__isnull=True):
        if share.burned_at is not None:
            consumed = True
            continue
        if share.expires_at <= now or not chain_is_live(share, now):
            continue
        key = (RANK[share.permission], not share.is_view_once, share.expires_at)
        if best is None or key > (RANK[best.permission], not best.is_view_once, best.expires_at):
            best = share
    return ShareAccess(share=best, consumed=consumed and best is None)
