"""Device registration, identification and trust management."""

import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions

from apps.accounts.models import User, UserSession
from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.policies.models import policy_for
from core import request_context
from core.exceptions import ServiceError
from core.permissions import Perm, has_perm

from . import anomaly
from .models import AnomalyAlert, Device, DeviceEvent

DEVICE_COOKIE = "sv_device"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
SEEN_INTERVAL = timedelta(minutes=5)
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_user_agent(user_agent: str) -> tuple[str, str]:
    """Coarse OS/browser labels for display. Informational only; user agents are trivially spoofed."""
    ua = user_agent or ""
    os_name = next(
        (
            label
            for pattern, label in (
                (r"Windows NT", "Windows"),
                (r"Android", "Android"),
                (r"iPhone|iPad|iPod", "iOS"),
                (r"Mac OS X|Macintosh", "macOS"),
                (r"CrOS", "ChromeOS"),
                (r"Linux", "Linux"),
            )
            if re.search(pattern, ua)
        ),
        "Unknown",
    )
    browser = next(
        (
            label
            for pattern, label in (
                (r"Edg/", "Edge"),
                (r"OPR/|Opera", "Opera"),
                (r"Firefox/", "Firefox"),
                (r"Chrome/|CriOS/", "Chrome"),
                (r"Safari/", "Safari"),
            )
            if re.search(pattern, ua)
        ),
        "Unknown",
    )
    return os_name, browser


def device_from_request(request) -> Device | None:
    """The device for this request's cookie, if it belongs to the signed-in user. Cached on the request."""
    if request is None:
        return None
    if hasattr(request, "_sv_device"):
        return request._sv_device
    device = None
    raw = request.COOKIES.get(DEVICE_COOKIE)
    user = getattr(request, "user", None)
    if raw and user is not None and user.is_authenticated:
        device = Device.objects.filter(token_hash=hash_token(raw), user_id=user.pk).first()
    request._sv_device = device
    return device


def current_device() -> Device | None:
    ctx = request_context.current()
    return device_from_request(ctx.request) if ctx else None


def set_device_cookie(response, raw_token: str) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        raw_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Strict",
        path="/",
    )


def _link_session(request, device: Device) -> None:
    key = getattr(request.session, "session_key", None)
    if key:
        UserSession.objects.filter(session_key=key, user=device.user).update(device=device)


def touch(device: Device, ip: str | None) -> None:
    now = timezone.now()
    if device.last_seen_at and now - device.last_seen_at < SEEN_INTERVAL and device.last_ip == ip:
        return
    Device.objects.filter(pk=device.pk).update(last_seen_at=now, last_ip=ip)
    DeviceEvent.objects.create(device=device, kind=DeviceEvent.Kind.SEEN, ip_address=ip)


def register_or_refresh(request, *, name: str, fingerprint: str) -> tuple[Device, str | None]:
    """Recognise this browser's device or register a new one. Returns (device, raw token if newly issued)."""
    user: User = request.user
    ctx = request_context.current()
    ip = ctx.ip_address if ctx else None
    fingerprint = fingerprint.lower() if _FINGERPRINT.match(fingerprint.lower()) else ""
    existing = device_from_request(request)

    if existing is not None and existing.trust_state != Device.Trust.REVOKED:
        if fingerprint and existing.fingerprint_hash and fingerprint != existing.fingerprint_hash:
            DeviceEvent.objects.create(device=existing, kind=DeviceEvent.Kind.FINGERPRINT_MISMATCH, ip_address=ip)
            anomaly.raise_alert(
                user=user,
                type=AnomalyAlert.Type.FINGERPRINT_MISMATCH,
                severity=AnomalyAlert.Severity.MEDIUM,
                summary=f'Signals from device "{existing.name}" changed (possible copied cookie).',
                device=existing,
                ip=ip,
            )
        elif fingerprint and not existing.fingerprint_hash:
            Device.objects.filter(pk=existing.pk).update(fingerprint_hash=fingerprint)
        touch(existing, ip)
        _link_session(request, existing)
        return existing, None

    os_name, browser = parse_user_agent(ctx.user_agent if ctx else "")
    raw_token = secrets.token_urlsafe(32)
    had_devices = Device.objects.filter(user=user).exclude(trust_state=Device.Trust.REVOKED).exists()
    with transaction.atomic():
        device = Device.objects.create(
            organization=user.organization,
            user=user,
            name=(name.strip() or f"{browser} on {os_name}")[:100],
            token_hash=hash_token(raw_token),
            fingerprint_hash=fingerprint,
            os=os_name,
            browser=browser,
            user_agent=(ctx.user_agent if ctx else "")[:300],
            first_ip=ip,
            last_ip=ip,
            last_seen_at=timezone.now(),
        )
        DeviceEvent.objects.create(device=device, kind=DeviceEvent.Kind.REGISTERED, ip_address=ip)
        audit.record(
            AuditAction.CREATE,
            actor=user,
            target=device,
            target_type="device",
            metadata={"os": os_name, "browser": browser},
        )
        notify(
            [user],
            Notification.Type.DEVICE_TRUST_CHANGED,
            f'New device registered: "{device.name}"',
            "If this was not you, contact your security team immediately.",
            priority=Notification.Priority.HIGH,
            link="/devices",
        )
        if policy_for(user.organization).require_device_trust:
            admins = [
                u
                for u in User.objects.filter(organization=user.organization, status=User.Status.ACTIVE)
                if has_perm(u, Perm.DEVICES_MANAGE) and u.pk != user.pk
            ]
            notify(
                admins,
                Notification.Type.DEVICE_TRUST_CHANGED,
                f"{user.full_name} registered a device awaiting approval",
                f'"{device.name}" ({browser} on {os_name})',
                link="/devices",
            )
    _link_session(request, device)
    if had_devices:
        anomaly.raise_alert(
            user=user,
            type=AnomalyAlert.Type.NEW_DEVICE,
            severity=AnomalyAlert.Severity.LOW,
            summary=f'{user.full_name} signed in from a new device ("{device.name}").',
            device=device,
            ip=ip,
        )
    return device, raw_token


_TRANSITIONS = {
    "approve": Device.Trust.TRUSTED,
    "suspend": Device.Trust.SUSPENDED,
    "revoke": Device.Trust.REVOKED,
}


def change_trust(*, actor: User, device: Device, operation: str, reason: str = "") -> Device:
    """approve / suspend: device administrators, never on their own device. revoke: administrators or the owner."""
    new_state = _TRANSITIONS[operation]
    is_admin = has_perm(actor, Perm.DEVICES_MANAGE)
    if device.organization_id != actor.organization_id:
        raise exceptions.NotFound()
    if operation in ("approve", "suspend"):
        if not is_admin:
            raise exceptions.PermissionDenied("Only device administrators can do this.", code="permission_denied")
        if device.user_id == actor.pk:
            raise ServiceError("You cannot change trust for your own device. Ask another administrator.", "self_change")
    elif not (is_admin or device.user_id == actor.pk):
        raise exceptions.PermissionDenied("You can only revoke your own devices.", code="permission_denied")

    from apps.accounts.services import revoke_sessions_for_device  # local: accounts must not import devices

    with transaction.atomic():
        locked = Device.objects.select_for_update().get(pk=device.pk)
        if locked.trust_state == Device.Trust.REVOKED:
            raise ServiceError("This device has been revoked. It must register again.", "revoked", status_code=409)
        previous = locked.trust_state
        locked.trust_state = new_state
        locked.trust_changed_by = actor
        locked.trust_changed_at = timezone.now()
        locked.trust_reason = reason.strip()[:300]
        locked.save(update_fields=["trust_state", "trust_changed_by", "trust_changed_at", "trust_reason", "updated_at"])
        DeviceEvent.objects.create(
            device=locked,
            kind=DeviceEvent.Kind.TRUST_CHANGED,
            details={"from": previous, "to": new_state, "by": str(actor.pk)},
        )
        audit.record(
            AuditAction.DEVICE_TRUST_CHANGE,
            actor=actor,
            target=locked,
            target_type="device",
            reason=locked.trust_reason,
            metadata={"from": previous, "to": new_state, "owner_id": str(locked.user_id)},
        )
        killed = 0
        if new_state in (Device.Trust.SUSPENDED, Device.Trust.REVOKED):
            killed = revoke_sessions_for_device(locked)  # signs the device out everywhere
        notify(
            [locked.user],
            Notification.Type.DEVICE_TRUST_CHANGED,
            f'Device "{locked.name}" is now {new_state.lower()}',
            locked.trust_reason or ("Signed out on that device." if killed else ""),
            link="/devices",
        )
    return locked
