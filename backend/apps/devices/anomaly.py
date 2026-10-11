"""Transparent, rule-based anomaly detection. No machine learning, no claim of completeness.

Rules (all thresholds are constants below, documented in docs/security-model.md):
  NEW_DEVICE            a user who already has a device registers another one              LOW
  NEW_NETWORK           successful sign-in from an IP prefix (/24 IPv4, /48 IPv6) never      MEDIUM
                        seen in that user's last 200 successful sign-ins
  FINGERPRINT_MISMATCH  a device cookie arrives with different browser signals             MEDIUM
  UNTRUSTED_DEVICE      a sensitive action was blocked by the device-trust policy           MEDIUM
  REVEAL_BURST          more than REVEAL_BURST_LIMIT reveals/copies within the window       HIGH

Limitations: no IP geolocation database is used (so "location" means network prefix), VPNs and mobile
networks cause false positives, and an attacker who stays under the thresholds is not detected.
"""

import ipaddress
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.notifications.models import Notification
from apps.notifications.services import notify
from core.permissions import Perm, has_perm

from .models import AnomalyAlert

logger = logging.getLogger(__name__)

DEDUPE_WINDOW = timedelta(minutes=60)
REVEAL_BURST_LIMIT = 20
REVEAL_BURST_WINDOW = timedelta(minutes=10)
LOGIN_HISTORY = 200

_PRIORITY = {
    AnomalyAlert.Severity.LOW: Notification.Priority.NORMAL,
    AnomalyAlert.Severity.MEDIUM: Notification.Priority.HIGH,
    AnomalyAlert.Severity.HIGH: Notification.Priority.CRITICAL,
}
_TELL_THE_USER = {
    AnomalyAlert.Type.NEW_NETWORK,
    AnomalyAlert.Type.UNTRUSTED_DEVICE,
    AnomalyAlert.Type.FINGERPRINT_MISMATCH,
}


def _security_admins(organization):
    return [
        u
        for u in User.objects.filter(organization=organization, status=User.Status.ACTIVE)
        if has_perm(u, Perm.ALERTS_MANAGE)
    ]


def raise_alert(*, user, type, severity, summary, details=None, device=None, ip=None) -> AnomalyAlert | None:
    """Create an alert unless an open one of the same type (and device) was raised for the user recently."""
    try:
        recent = AnomalyAlert.objects.filter(
            user=user, type=type, status=AnomalyAlert.Status.OPEN, created_at__gte=timezone.now() - DEDUPE_WINDOW
        )
        if device is not None:
            recent = recent.filter(device=device)
        if recent.exists():
            return None
        with transaction.atomic():
            alert = AnomalyAlert.objects.create(
                organization_id=user.organization_id,
                user=user,
                device=device,
                type=type,
                severity=severity,
                summary=summary[:300],
                details=details or {},
                ip_address=ip,
            )
            notify(
                _security_admins(user.organization),
                Notification.Type.SUSPICIOUS_ACTIVITY,
                summary,
                f"Severity: {severity.lower()}. Review it in Security alerts.",
                priority=_PRIORITY[severity],
                link="/alerts",
            )
            if type in _TELL_THE_USER:
                notify(
                    [user],
                    Notification.Type.SUSPICIOUS_ACTIVITY,
                    "Security check on your account",
                    summary,
                    priority=_PRIORITY[severity],
                    link="/devices",
                )
        return alert
    except Exception:
        # Detection is best-effort: it must never turn a legitimate action into an error.
        logger.exception("Could not record anomaly alert %s", type)
        return None


def _prefix(ip: str):
    address = ipaddress.ip_address(ip)
    return ipaddress.ip_network(f"{ip}/{24 if address.version == 4 else 48}", strict=False)


def evaluate_login(user, ip: str | None) -> None:
    """Call BEFORE recording the new LOGIN audit row, so history contains only earlier sign-ins."""
    if not ip:
        return
    previous = list(
        AuditLog.objects.filter(
            actor_id=user.pk, action=AuditAction.LOGIN, outcome=AuditOutcome.SUCCESS, ip_address__isnull=False
        )
        .order_by("-id")
        .values_list("ip_address", flat=True)[:LOGIN_HISTORY]
    )
    if not previous:
        return  # first sign-in: nothing to compare against
    current = _prefix(ip)
    if any(ipaddress.ip_address(p) in current for p in previous):
        return
    raise_alert(
        user=user,
        type=AnomalyAlert.Type.NEW_NETWORK,
        severity=AnomalyAlert.Severity.MEDIUM,
        summary=f"{user.full_name} signed in from an unfamiliar network ({current}).",
        details={"network": str(current)},
        ip=ip,
    )


def evaluate_reveal_burst(user) -> None:
    since = timezone.now() - REVEAL_BURST_WINDOW
    count = AuditLog.objects.filter(
        actor_id=user.pk,
        action__in=[AuditAction.REVEAL, AuditAction.COPY],
        outcome=AuditOutcome.SUCCESS,
        created_at__gte=since,
    ).count()
    if count > REVEAL_BURST_LIMIT:
        minutes = int(REVEAL_BURST_WINDOW.total_seconds() // 60)
        raise_alert(
            user=user,
            type=AnomalyAlert.Type.REVEAL_BURST,
            severity=AnomalyAlert.Severity.HIGH,
            summary=f"{user.full_name} revealed {count} secrets in {minutes} minutes.",
            details={"count": count},
        )
