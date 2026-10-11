"""Account business rules: login lockout, session revocation, invitations, user administration.

Views stay thin and call these functions; every multi-step change runs in a transaction.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from core.exceptions import ServiceError

from .models import Invitation, User, UserSession

# --------------------------------------------------------------------------- login lockout


def _failure_key(email: str) -> str:
    # Keyed by a hash of the submitted email (existing or not), so lockout reveals nothing
    # about which accounts exist and raw emails are not stored in the cache.
    return "auth:fail:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def is_login_locked(email: str) -> bool:
    return cache.get(_failure_key(email), 0) >= settings.LOGIN_LOCKOUT_THRESHOLD


def record_login_failure(email: str) -> None:
    key = _failure_key(email)
    cache.add(key, 0, timeout=settings.LOGIN_LOCKOUT_SECONDS)
    cache.incr(key)


def clear_login_failures(email: str) -> None:
    cache.delete(_failure_key(email))


# --------------------------------------------------------------------------- sessions


def record_session(request, user: User) -> None:
    session_key = request.session.session_key
    if not session_key:
        return
    UserSession.objects.update_or_create(
        session_key=session_key,
        defaults={
            "user": user,
            "ip_address": request.META.get("REMOTE_ADDR") or None,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300],
        },
    )


def forget_session(session_key: str | None) -> None:
    if session_key:
        UserSession.objects.filter(session_key=session_key).delete()


def revoke_sessions(users) -> int:
    """Delete every server-side session of `users` (a queryset or iterable). Returns live sessions killed."""
    keys = list(UserSession.objects.filter(user__in=users).values_list("session_key", flat=True))
    with transaction.atomic():
        live = Session.objects.filter(session_key__in=keys, expire_date__gt=timezone.now()).count()
        Session.objects.filter(session_key__in=keys).delete()
        UserSession.objects.filter(session_key__in=keys).delete()
    return live


# --------------------------------------------------------------------------- invitations

INVALID_INVITATION = "This invitation link is invalid or has expired."


def hash_token(raw_token: str) -> str:
    # Tokens are 256-bit random values, so a fast unsalted hash is sufficient here
    # (unlike passwords, they cannot be brute-forced from the hash).
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _issue_invitation(user: User, inviter: User) -> tuple[Invitation, str]:
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        organization=user.organization,
        user=user,
        invited_by=inviter,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=settings.INVITATION_TTL_HOURS),
    )
    return invitation, raw_token


def invitation_url(raw_token: str) -> str:
    # The token travels in the URL fragment, which browsers never send to servers,
    # so it does not end up in access logs or Referer headers.
    return f"{settings.FRONTEND_URL}/accept-invite#token={raw_token}"


@transaction.atomic
def invite_user(*, inviter: User, email: str, full_name: str, role: str, department=None) -> tuple[Invitation, str]:
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise ServiceError("A user with this email already exists.", "email_taken")
    user = User.objects.create_user(
        email,
        inviter.organization,
        None,
        full_name=full_name.strip(),
        role=role,
        department=department,
        status=User.Status.INVITED,
    )
    return _issue_invitation(user, inviter)


@transaction.atomic
def resend_invitation(*, inviter: User, invitation: Invitation) -> tuple[Invitation, str]:
    user = User.objects.select_for_update().get(pk=invitation.user_id)
    if user.status != User.Status.INVITED:
        raise ServiceError("This user is no longer awaiting activation.", "not_invited")
    Invitation.objects.filter(user=user, accepted_at__isnull=True, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    return _issue_invitation(user, inviter)


@transaction.atomic
def revoke_invitation(invitation: Invitation) -> Invitation:
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.state != "PENDING":
        raise ServiceError("Only pending invitations can be revoked.", "not_pending")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at", "updated_at"])
    return invitation


@transaction.atomic
def accept_invitation(*, raw_token: str, password: str) -> User:
    """Activate an invited user. Single use: the row lock serialises concurrent attempts."""
    try:
        invitation = (
            Invitation.objects.select_for_update(of=("self",))
            .select_related("user__organization")
            .get(token_hash=hash_token(raw_token))
        )
    except Invitation.DoesNotExist:
        raise ServiceError(INVALID_INVITATION, "invalid_invitation") from None

    user = invitation.user
    if (
        invitation.state != "PENDING"
        or user.status != User.Status.INVITED
        or user.organization.status != "ACTIVE"
    ):
        raise ServiceError(INVALID_INVITATION, "invalid_invitation")

    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        # Raised before anything is written, so a weak password does not consume the invitation.
        raise ServiceError(
            "Password does not meet the requirements.", "weak_password", details={"password": exc.messages}
        ) from None

    user.set_password(password)
    user.status = User.Status.ACTIVE
    user.save(update_fields=["password", "status", "updated_at"])
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at", "updated_at"])
    return user


# --------------------------------------------------------------------------- user administration


@transaction.atomic
def update_user(*, actor: User, user: User, changes: dict) -> User:
    """Apply admin edits (full_name, role, status, department) with safety rules."""
    # Lock the organization's active admins first, in a fixed order, so two admins
    # demoting each other concurrently cannot both succeed (or deadlock).
    active_admins = list(
        User.objects.select_for_update()
        .filter(organization=actor.organization, role=User.Role.ORG_ADMIN, status=User.Status.ACTIVE)
        .order_by("pk")
    )
    user = User.objects.select_for_update().get(pk=user.pk)

    new_role = changes.get("role", user.role)
    new_status = changes.get("status", user.status)

    if user.pk == actor.pk and (new_role != user.role or new_status != user.status):
        raise ServiceError("You cannot change your own role or status.", "self_change")

    if new_status != user.status:
        if new_status == User.Status.INVITED:
            raise ServiceError("A user cannot be moved back to Invited.", "invalid_status")
        if user.status == User.Status.INVITED and new_status != User.Status.DEACTIVATED:
            raise ServiceError("Invited users activate through their invitation link.", "invalid_status")

    loses_admin = user.role == User.Role.ORG_ADMIN and user.status == User.Status.ACTIVE and (
        new_role != User.Role.ORG_ADMIN or new_status != User.Status.ACTIVE
    )
    if loses_admin and not any(admin.pk != user.pk for admin in active_admins):
        raise ServiceError(
            "The organization must keep at least one active Organization Administrator.", "last_admin"
        )

    was_active = user.status == User.Status.ACTIVE
    for field in ("full_name", "role", "status", "department"):
        if field in changes:
            setattr(user, field, changes[field])
    user.save()

    if new_status == User.Status.DEACTIVATED:
        Invitation.objects.filter(user=user, accepted_at__isnull=True, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    if was_active and new_status != User.Status.ACTIVE:
        # Same transaction as the status change: both commit together or neither does.
        revoke_sessions([user])
    return user
