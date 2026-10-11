from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.policies.models import policy_for
from apps.sharing.access import RANK
from apps.sharing.services import create_share
from apps.vault.models import Credential
from core.exceptions import ServiceError

from .models import PENDING_LIFETIME, AccessRequest


def _max_hours(organization) -> int:
    return policy_for(organization).max_share_duration_days * 24


def create_request(*, requester, credential: Credential, permission: str, duration_hours: int, reason: str):
    if credential.organization_id != requester.organization_id or not credential.requestable or credential.is_archived:
        raise ServiceError("This credential is not open to access requests.", "not_requestable", status_code=404)
    if credential.owner_id == requester.pk:
        raise ServiceError("You already own this credential.", "already_has_access", status_code=409)
    if not 1 <= duration_hours <= _max_hours(requester.organization):
        raise ServiceError(
            f"Choose a duration between 1 and {_max_hours(requester.organization)} hours.", "invalid_duration"
        )
    access = credential.access_for(requester, fresh=True)
    if access.share is not None and RANK[access.share.permission] >= RANK[permission]:
        raise ServiceError("You already have this level of access.", "already_has_access", status_code=409)

    now = timezone.now()
    with transaction.atomic():
        pending = (
            AccessRequest.objects.select_for_update()
            .filter(credential=credential, requester=requester, status=AccessRequest.Status.PENDING)
            .first()
        )
        if pending is not None:
            if pending.expires_at > now:
                raise ServiceError(
                    "You already have a pending request for this credential.", "duplicate_request", status_code=409
                )
            pending.status = AccessRequest.Status.CANCELLED  # lapsed: make room for the new one
            pending.decision_note = "expired"
            pending.save(update_fields=["status", "decision_note", "updated_at"])

        request = AccessRequest.objects.create(
            organization=requester.organization,
            credential=credential,
            requester=requester,
            permission=permission,
            requested_duration_hours=duration_hours,
            reason=reason.strip(),
            expires_at=now + PENDING_LIFETIME,
        )
        audit.record(
            AuditAction.ACCESS_REQUEST,
            actor=requester,
            target=credential,
            target_type="credential",
            metadata={"request_id": str(request.pk), "permission": permission, "duration_hours": duration_hours},
        )
        notify(
            [credential.owner],
            Notification.Type.ACCESS_REQUEST,
            f'{requester.full_name} requests access to "{credential.title}"',
            f"{permission.title()} for {duration_hours} h. Reason: {request.reason[:300]}",
            link="/access-requests",
        )
    return request


def _decidable(request: AccessRequest, approver) -> AccessRequest:
    locked = AccessRequest.objects.select_for_update().select_related("credential", "requester").get(pk=request.pk)
    if locked.credential.owner_id != approver.pk:
        raise exceptions.PermissionDenied("Only the credential's owner can decide this request.", code="not_owner")
    if locked.state(timezone.now()) != AccessRequest.Status.PENDING:
        raise ServiceError("This request is no longer pending.", "not_pending", status_code=409)
    return locked


def approve(*, approver, request: AccessRequest, duration_hours: int | None = None, permission: str | None = None):
    with transaction.atomic():
        locked = _decidable(request, approver)
        permission = permission or locked.permission
        if RANK[permission] > RANK[locked.permission]:
            raise ServiceError("You cannot grant more than was requested.", "exceeds_request")
        hours = duration_hours or locked.requested_duration_hours
        if not 1 <= hours <= locked.requested_duration_hours:
            raise ServiceError("The duration must be between 1 hour and the requested duration.", "invalid_duration")

        share = create_share(
            actor=approver,
            credential=locked.credential,
            grantee=locked.requester,
            permission=permission,
            expires_at=timezone.now() + timedelta(hours=hours),
        )
        locked.status = AccessRequest.Status.APPROVED
        locked.approver = approver
        locked.decided_at = timezone.now()
        locked.share = share
        locked.save(update_fields=["status", "approver", "decided_at", "share", "updated_at"])
        audit.record(
            AuditAction.APPROVAL,
            actor=approver,
            target=locked.credential,
            target_type="credential",
            metadata={
                "request_id": str(locked.pk),
                "share_id": str(share.pk),
                "hours": hours,
                "permission": permission,
            },
        )
        notify(
            [locked.requester],
            Notification.Type.ACCESS_APPROVED,
            f'Access to "{locked.credential.title}" approved',
            f"{permission.title()} for {hours} h.",
            link="/vault",
        )
    return locked


def reject(*, approver, request: AccessRequest, note: str = ""):
    with transaction.atomic():
        locked = _decidable(request, approver)
        locked.status = AccessRequest.Status.REJECTED
        locked.approver = approver
        locked.decided_at = timezone.now()
        locked.decision_note = note.strip()[:500]
        locked.save(update_fields=["status", "approver", "decided_at", "decision_note", "updated_at"])
        audit.record(
            AuditAction.REJECTION,
            actor=approver,
            target=locked.credential,
            target_type="credential",
            metadata={"request_id": str(locked.pk)},
        )
        notify(
            [locked.requester],
            Notification.Type.ACCESS_REJECTED,
            f'Access to "{locked.credential.title}" was declined',
            locked.decision_note,
            link="/access-requests",
        )
    return locked


def cancel(*, requester, request: AccessRequest):
    with transaction.atomic():
        locked = AccessRequest.objects.select_for_update().get(pk=request.pk)
        if locked.requester_id != requester.pk:
            raise exceptions.PermissionDenied("Only the requester can cancel this request.", code="not_requester")
        if locked.status != AccessRequest.Status.PENDING:
            raise ServiceError("This request is no longer pending.", "not_pending", status_code=409)
        locked.status = AccessRequest.Status.CANCELLED
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_at", "updated_at"])
    return locked
