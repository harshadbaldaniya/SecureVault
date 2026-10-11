"""The single authorization gate for sensitive actions on protected resources.

Zero-trust rule: a successful login is never enough. Every reveal, copy, edit, delete or
share of a protected resource must pass `authorize()`, which evaluates in order:

  1. identity, organization membership and account status
  2. the resource's own permission set for this user (owner / share grants)
  3. every registered sensitive-action check (share validity, device trust, anomaly
     policy, active lockdown ...). Later phases add their checks with `register_check`.

The gate runs on the server for every request. WebSocket messages and UI state are never
a substitute for it. Call it *before* opening a database transaction so that the DENIED
audit record it writes is not rolled back together with the refused action.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from rest_framework import exceptions

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditOutcome


class Action(StrEnum):
    VIEW = "VIEW"
    REVEAL = "REVEAL"
    COPY = "COPY"
    EDIT = "EDIT"
    DELETE = "DELETE"
    SHARE = "SHARE"


SENSITIVE_ACTIONS = frozenset({Action.REVEAL, Action.COPY, Action.EDIT, Action.DELETE, Action.SHARE})

_AUDIT_ACTION = {
    Action.REVEAL: AuditAction.REVEAL,
    Action.COPY: AuditAction.COPY,
    Action.EDIT: AuditAction.EDIT,
    Action.DELETE: AuditAction.DELETE,
    Action.SHARE: AuditAction.SHARE,
}


@dataclass(frozen=True)
class GateContext:
    user: object
    resource: object
    action: Action


Check = Callable[[GateContext], None]
_sensitive_checks: list[Check] = []


def register_check(check: Check) -> Check:
    """Register a check that runs for every sensitive action. It must raise a DRF exception to deny."""
    if check not in _sensitive_checks:
        _sensitive_checks.append(check)
    return check


def _deny(ctx: GateContext, message: str, code: str) -> None:
    audit_action = _AUDIT_ACTION.get(ctx.action)
    if audit_action is not None:
        audit.record(
            audit_action,
            actor=ctx.user,
            outcome=AuditOutcome.DENIED,
            target=ctx.resource,
            reason=code,
            fail_silently=True,  # a refusal must stay a refusal even if the audit store is down
        )
    raise exceptions.PermissionDenied(message, code=code)


def authorize(user, resource, action: Action) -> None:
    ctx = GateContext(user=user, resource=resource, action=action)

    # 1. identity, organization, account status
    if not (user.is_authenticated and user.is_active and user.organization.status == "ACTIVE"):
        _deny(ctx, "Your account cannot perform this action.", "account_inactive")
    if resource.organization_id != user.organization_id:
        _deny(ctx, "You do not have permission to do this.", "wrong_organization")

    # 2. resource-level permission
    if action not in resource.permissions_for(user):
        _deny(ctx, "You do not have permission to do this.", "permission_denied")

    # 3. sensitive-action checks (share validity, device trust, anomaly, lockdown ...)
    if action in SENSITIVE_ACTIONS:
        for check in _sensitive_checks:
            check(ctx)
