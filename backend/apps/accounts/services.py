"""Account business rules: login lockout, session revocation, invitations, user administration.

Views stay thin and call these functions; every multi-step change runs in a transaction.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction
from core.exceptions import ServiceError
from core.realtime import close_user_sockets

from .models import Invitation, PasswordResetToken, User, UserSession

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


def revoke_sessions(users, *, keep_session_key: str | None = None) -> int:
    """Delete every server-side session of `users` (a queryset or iterable), optionally sparing one.

    Returns the number of live sessions killed.
    """
    sessions = UserSession.objects.filter(user__in=users)
    if keep_session_key:
        sessions = sessions.exclude(session_key=keep_session_key)
    return _delete_sessions(sessions)


def revoke_sessions_for_device(device) -> int:
    """Sign a device out everywhere (used when its trust is suspended or revoked)."""
    return _delete_sessions(UserSession.objects.filter(device=device))


def _delete_sessions(sessions) -> int:
    rows = list(sessions.values_list("session_key", "user_id"))
    keys = [key for key, _ in rows]
    with transaction.atomic():
        live = Session.objects.filter(session_key__in=keys, expire_date__gt=timezone.now()).count()
        Session.objects.filter(session_key__in=keys).delete()
        UserSession.objects.filter(session_key__in=keys).delete()
        if rows:
            # Real-time sockets were authenticated with these sessions: drop them; clients whose session
            # survived simply reconnect, the others are refused at the handshake.
            user_ids = [user_id for _, user_id in rows]
            transaction.on_commit(lambda: close_user_sockets(user_ids))
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
    result = _issue_invitation(user, inviter)
    audit.record(AuditAction.INVITE, actor=inviter, target=user, target_type="user", metadata={"role": role})
    return result


@transaction.atomic
def resend_invitation(*, inviter: User, invitation: Invitation) -> tuple[Invitation, str]:
    user = User.objects.select_for_update().get(pk=invitation.user_id)
    if user.status != User.Status.INVITED:
        raise ServiceError("This user is no longer awaiting activation.", "not_invited")
    Invitation.objects.filter(user=user, accepted_at__isnull=True, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    result = _issue_invitation(user, inviter)
    audit.record(AuditAction.INVITE, actor=inviter, target=user, target_type="user", metadata={"resend": True})
    return result


@transaction.atomic
def revoke_invitation(invitation: Invitation) -> Invitation:
    invitation = Invitation.objects.select_for_update(of=("self",)).select_related("user").get(pk=invitation.pk)
    if invitation.state != "PENDING":
        raise ServiceError("Only pending invitations can be revoked.", "not_pending")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at", "updated_at"])
    audit.record(
        AuditAction.REVOKE, target=invitation, target_type="invitation", target_label=invitation.user.email
    )
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

    # Raised before anything is written, so a weak password does not consume the invitation.
    _validate_new_password(password, user)

    user.set_password(password)
    user.status = User.Status.ACTIVE
    user.save(update_fields=["password", "status", "updated_at"])
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at", "updated_at"])
    audit.record(AuditAction.ACCOUNT_ACTIVATE, actor=user, target=user, target_type="user")
    return user


# --------------------------------------------------------------------------- passwords

INVALID_RESET = "This password reset link is invalid or has expired."


def _issue_reset_token(user: User, issued_by: User | None) -> str:
    now = timezone.now()
    # Only the newest link works: issuing a new one retires any older unused links.
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    raw_token = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        issued_by=issued_by,
        token_hash=hash_token(raw_token),
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES),
    )
    return raw_token


def password_reset_url(raw_token: str) -> str:
    return f"{settings.FRONTEND_URL}/reset-password#token={raw_token}"


@transaction.atomic
def request_password_reset(email: str) -> None:
    """Self-service reset. Callers must answer identically whether or not the account exists."""
    user = (
        User.objects.select_related("organization")
        .filter(email__iexact=email.strip(), status=User.Status.ACTIVE, organization__status="ACTIVE")
        .first()
    )
    if user is None:
        audit.record(
            AuditAction.PASSWORD_RESET_REQUEST, outcome="FAILURE", target_type="user",
            target_label=email.strip().lower()[:254], reason="unknown_or_inactive", fail_silently=True,
        )
        return
    raw_token = _issue_reset_token(user, issued_by=None)
    audit.record(AuditAction.PASSWORD_RESET_REQUEST, organization=user.organization, target=user, target_type="user")
    link = password_reset_url(raw_token)
    # Sent only after the transaction commits, so a rolled-back request never emails a dead link.
    transaction.on_commit(
        lambda: send_mail(
            "SecureVault password reset",
            f"Use this link within {settings.PASSWORD_RESET_TTL_MINUTES} minutes to choose a new password:\n\n"
            f"{link}\n\nIf you did not ask for this, ignore this email.",
            None,
            [user.email],
        )
    )


@transaction.atomic
def issue_admin_reset_link(*, actor: User, user: User) -> str:
    """Admin-assisted recovery: returns a one-time link for out-of-band delivery."""
    if actor.pk == user.pk:
        raise ServiceError("Use password change for your own account.", "self_change")
    if user.status != User.Status.ACTIVE:
        raise ServiceError("Only active users can reset their password.", "invalid_status")
    raw_token = _issue_reset_token(user, issued_by=actor)
    audit.record(AuditAction.PASSWORD_RESET_REQUEST, actor=actor, target=user, target_type="user",
                 metadata={"issued_by_admin": True})
    return password_reset_url(raw_token)


@transaction.atomic
def confirm_password_reset(*, raw_token: str, password: str) -> User:
    try:
        token = (
            PasswordResetToken.objects.select_for_update(of=("self",))
            .select_related("user__organization")
            .get(token_hash=hash_token(raw_token))
        )
    except PasswordResetToken.DoesNotExist:
        raise ServiceError(INVALID_RESET, "invalid_reset_token") from None

    user = token.user
    if not token.is_usable or user.status != User.Status.ACTIVE or user.organization.status != "ACTIVE":
        raise ServiceError(INVALID_RESET, "invalid_reset_token")
    _validate_new_password(password, user)

    user.set_password(password)
    user.save(update_fields=["password", "updated_at"])
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    killed = revoke_sessions([user])
    clear_login_failures(user.email)
    audit.record(AuditAction.PASSWORD_RESET, actor=user, target=user, target_type="user",
                 metadata={"sessions_revoked": killed})
    return user


@transaction.atomic
def change_password(request, *, current_password: str, new_password: str) -> None:
    user = request.user
    if not user.check_password(current_password):
        raise ServiceError("Current password is incorrect.", "invalid_password")
    _validate_new_password(new_password, user)

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    # Keep this browser signed in (Django rotates the session key), end every other session.
    old_key = request.session.session_key
    update_session_auth_hash(request, user)
    forget_session(old_key)
    record_session(request, user)
    killed = revoke_sessions([user], keep_session_key=request.session.session_key)
    audit.record(AuditAction.PASSWORD_CHANGE, actor=user, target=user, target_type="user",
                 metadata={"other_sessions_revoked": killed})


def _validate_new_password(password: str, user: User) -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ServiceError(
            "Password does not meet the requirements.", "weak_password", details={"password": exc.messages}
        ) from None


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
    old_role, old_status = user.role, user.status
    for field in ("full_name", "role", "status", "department"):
        if field in changes:
            setattr(user, field, changes[field])
    user.save()

    metadata = {"changed": sorted(changes)}
    if new_role != old_role:
        metadata["role"] = {"from": old_role, "to": new_role}
    if new_status != old_status:
        metadata["status"] = {"from": old_status, "to": new_status}
    audit.record(AuditAction.EDIT, actor=actor, target=user, target_type="user", metadata=metadata)

    if new_status == User.Status.DEACTIVATED and old_status != User.Status.DEACTIVATED:
        from apps.sharing.services import revoke_received_grants  # local import: sharing builds on accounts

        Invitation.objects.filter(user=user, accepted_at__isnull=True, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        revoked = revoke_received_grants(actor=actor, user=user, reason="account_deactivated")
        if revoked:
            audit.record(AuditAction.REVOKE, actor=actor, target=user, target_type="user",
                         metadata={"reason": "account_deactivated", "revoked_grants": revoked})
    if was_active and new_status != User.Status.ACTIVE:
        # Same transaction as the status change: both commit together or neither does.
        revoke_sessions([user])
    return user
