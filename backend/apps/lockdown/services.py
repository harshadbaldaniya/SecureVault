"""Emergency lockdown: activate, resolve, and the server-side checks that enforce it.

Enforcement never depends on WebSockets. The lockdown row is committed first (phase A); from that instant
every sensitive request, every sign-in and every WebSocket handshake checks it. Notifications and the
WebSocket broadcast follow the commit; session termination runs right after (phase B).
"""

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import exceptions

from apps.accounts.mfa import verify_reauthentication
from apps.accounts.models import User
from apps.accounts.services import revoke_sessions
from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.notifications.models import Notification
from apps.notifications.services import notify
from core import realtime
from core.exceptions import ServiceError
from core.permissions import Perm, has_perm

from .models import LockdownState

MIN_REASON_LENGTH = 10


class LockdownActive(exceptions.APIException):
    status_code = 423
    default_code = "lockdown_active"
    default_detail = "SecureVault is in emergency lockdown. Sensitive actions are blocked until it is lifted."


def applicable(user) -> LockdownState | None:
    """The active lockdown that covers this user (organization-wide or targeted), if any."""
    return (
        LockdownState.objects.filter(organization_id=user.organization_id, is_active=True)
        .filter(Q(scope=LockdownState.Scope.GLOBAL) | Q(target_user_id=user.pk))
        .order_by("-scope")  # USER before GLOBAL: the more specific state wins for display
        .first()
    )


def blocks_session(user, state: LockdownState) -> bool:
    """Whether this user may not be signed in at all. Administrators stay signed in during a global
    lockdown to manage the incident (but still cannot use secrets); a targeted user is always locked out."""
    if state.scope == LockdownState.Scope.USER:
        return True
    return not has_perm(user, Perm.LOCKDOWN_MANAGE)


def session_block(user) -> LockdownState | None:
    state = applicable(user)
    return state if state is not None and blocks_session(user, state) else None


def payload(state: LockdownState | None) -> dict | None:
    if state is None:
        return None
    return {
        "id": str(state.pk),
        "scope": state.scope,
        "target_user_id": str(state.target_user_id) if state.target_user_id else None,
        "triggered_at": state.created_at.isoformat(),
        "is_active": state.is_active,
    }


def _require_manager(actor) -> None:
    if not has_perm(actor, Perm.LOCKDOWN_MANAGE):
        raise exceptions.PermissionDenied(
            "Only security administrators can manage lockdowns.", code="permission_denied"
        )


def _broadcast(state: LockdownState, event: str, blocked_user_ids: list) -> None:
    message = {"type": event, "lockdown": payload(state)}
    if state.scope == LockdownState.Scope.GLOBAL:
        realtime.push_to_org(state.organization_id, message)
    else:
        realtime.push_to_user(state.target_user_id, message)
    if blocked_user_ids:
        realtime.close_user_sockets(blocked_user_ids, realtime.CLOSE_LOCKDOWN)


def activate(*, actor: User, scope: str, reason: str, password: str, code: str = "", target_user: User | None = None):
    _require_manager(actor)
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ServiceError(f"Give a reason of at least {MIN_REASON_LENGTH} characters.", "reason_required")
    if scope == LockdownState.Scope.USER:
        if target_user is None or target_user.organization_id != actor.organization_id:
            raise ServiceError("Choose a user in your organization.", "invalid_target")
        if target_user.pk == actor.pk:
            raise ServiceError("You cannot lock yourself out.", "self_change")
    else:
        target_user = None
    verify_reauthentication(actor, password, code)

    # Phase A: the lockdown exists (and is enforced everywhere) as soon as this commits.
    org_users = User.objects.filter(organization_id=actor.organization_id)
    try:
        with transaction.atomic():
            state = LockdownState.objects.create(
                organization_id=actor.organization_id,
                scope=scope,
                target_user=target_user,
                reason=reason[:500],
                initiated_by=actor,
            )
            audit.record(
                AuditAction.LOCKDOWN,
                actor=actor,
                target_type="lockdown",
                target_id=str(state.pk),
                target_label=scope,
                reason=reason[:500],
                metadata={
                    "operation": "activate",
                    "scope": scope,
                    "target_user_id": str(target_user.pk) if target_user else None,
                },
            )
            if scope == LockdownState.Scope.GLOBAL:
                blocked = [u for u in org_users.filter(status=User.Status.ACTIVE) if blocks_session(u, state)]
            else:
                blocked = [target_user]
            blocked_ids = [u.pk for u in blocked]
            transaction.on_commit(lambda: _broadcast(state, "lockdown.activated", blocked_ids))
    except IntegrityError:
        raise ServiceError("A lockdown with this scope is already active.", "already_active", status_code=409) from None

    # Phase B: terminate the sessions of everyone who may no longer be signed in, then tell people.
    with transaction.atomic():
        killed = revoke_sessions(blocked)
        LockdownState.objects.filter(pk=state.pk).update(terminated_session_count=killed)
        state.terminated_session_count = killed
        recipients = (
            org_users.filter(status=User.Status.ACTIVE)
            if scope == LockdownState.Scope.GLOBAL
            else (
                [target_user]
                + [u for u in org_users.filter(status=User.Status.ACTIVE) if has_perm(u, Perm.LOCKDOWN_MANAGE)]
            )
        )
        notify(
            recipients,
            Notification.Type.LOCKDOWN,
            "Emergency lockdown activated" if scope == LockdownState.Scope.GLOBAL else "An account was locked down",
            "Access to secrets is frozen until the security team lifts the lockdown.",
            priority=Notification.Priority.CRITICAL,
            link="/lockdown",
        )
    return state


def resolve(*, actor: User, state: LockdownState, note: str, password: str, code: str = "") -> LockdownState:
    _require_manager(actor)
    if state.organization_id != actor.organization_id:
        raise exceptions.NotFound()
    verify_reauthentication(actor, password, code)
    with transaction.atomic():
        locked = LockdownState.objects.select_for_update().get(pk=state.pk)
        if not locked.is_active:
            raise ServiceError("This lockdown has already been lifted.", "not_active", status_code=409)
        locked.is_active = False
        locked.resolved_at = timezone.now()
        locked.resolved_by = actor
        locked.resolution_note = (note or "").strip()[:500]
        locked.save(update_fields=["is_active", "resolved_at", "resolved_by", "resolution_note", "updated_at"])
        audit.record(
            AuditAction.LOCKDOWN,
            actor=actor,
            target_type="lockdown",
            target_id=str(locked.pk),
            target_label=locked.scope,
            reason=locked.resolution_note,
            metadata={"operation": "resolve", "scope": locked.scope},
        )
        recipients = (
            User.objects.filter(organization_id=actor.organization_id, status=User.Status.ACTIVE)
            if locked.scope == LockdownState.Scope.GLOBAL
            else [locked.target_user]
        )
        notify(recipients, Notification.Type.LOCKDOWN, "Lockdown lifted", locked.resolution_note, link="/")
        transaction.on_commit(lambda: _broadcast(locked, "lockdown.resolved", []))
    return locked


def lockdown_check(ctx) -> None:
    """Zero-trust pipeline step 8: no sensitive action while an applicable lockdown is active (for anyone)."""
    if applicable(ctx.user) is not None:
        raise LockdownActive()
