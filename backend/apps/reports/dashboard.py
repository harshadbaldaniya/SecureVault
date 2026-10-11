"""One request for the home dashboard. Counts only: no secret, ciphertext or blind index leaves the server.

`me` is computed for every user; `organization` only for people allowed to see organization reports.
"""

from datetime import datetime, time, timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_requests.models import AccessRequest
from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.devices.models import AnomalyAlert, Device
from apps.lockdown.models import LockdownState
from apps.lockdown.services import payload
from apps.notifications.models import Notification
from apps.policies.models import policy_for
from apps.sharing.models import Share
from apps.vault.models import Credential
from apps.vault.strength import LABELS, strength_label
from core.permissions import Perm, has_perm

STRENGTH_ORDER = [label for _, label in LABELS] + ["very_strong"]
SECURITY_EVENTS = [
    AuditAction.LOCKDOWN,
    AuditAction.DEVICE_TRUST_CHANGE,
    AuditAction.REVOKE,
    AuditAction.POLICY_CHANGE,
    AuditAction.MFA_RESET,
    AuditAction.KEY_ROTATION,
]


def _live_shares(now):
    return Share.objects.filter(revoked_at__isnull=True, burned_at__isnull=True, expires_at__gt=now)


def _activity(organization, user, now, days=7):
    """Successful reveals + copies per day for the last `days` days (oldest first, zero-filled)."""
    start = timezone.localdate(now) - timedelta(days=days - 1)
    # A plain range on created_at (not created_at__date) so the (organization, action, created_at) index applies.
    since = timezone.make_aware(datetime.combine(start, time.min))
    rows = (
        AuditLog.objects.filter(
            organization=organization,
            action__in=[AuditAction.REVEAL, AuditAction.COPY],
            outcome=AuditOutcome.SUCCESS,
            created_at__gte=since,
            **({"actor_id": user.pk} if user is not None else {}),
        )
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(n=Count("id"))
    )
    counts = {row["day"]: row["n"] for row in rows}
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "count": counts.get(start + timedelta(days=i), 0)}
        for i in range(days)
    ]


def personal(user, now) -> dict:
    today = now.date()
    warning = policy_for(user.organization).expiry_warning_days
    mine = Credential.objects.filter(organization=user.organization, owner=user, archived_at__isnull=True)
    entropy = list(mine.values_list("entropy_bits", flat=True))
    distribution = dict.fromkeys(STRENGTH_ORDER, 0)
    for bits in entropy:
        distribution[strength_label(bits)] += 1
    reused = mine.values("blind_index", "blind_index_version").annotate(n=Count("id")).filter(n__gt=1)
    devices = Device.objects.filter(user=user).exclude(trust_state=Device.Trust.REVOKED)
    pending_for_me = AccessRequest.objects.filter(
        credential__owner=user, status=AccessRequest.Status.PENDING, expires_at__gt=now
    )
    return {
        "credentials": len(entropy),
        "shared_with_me": _live_shares(now)
        .filter(grantee=user, credential__archived_at__isnull=True)
        .values("credential")
        .distinct()
        .count(),
        "shares_given": _live_shares(now).filter(grantor=user).count(),
        "requests_to_approve": pending_for_me.count(),
        "my_pending_requests": AccessRequest.objects.filter(
            requester=user, status=AccessRequest.Status.PENDING, expires_at__gt=now
        ).count(),
        "expiring_soon": mine.filter(expires_at__gte=today, expires_at__lte=today + timedelta(days=warning)).count(),
        "expired": mine.filter(expires_at__lt=today).count(),
        "weak": distribution["very_weak"] + distribution["weak"],
        "reused": sum(row["n"] for row in reused),
        "strength": [{"label": label, "count": distribution[label]} for label in STRENGTH_ORDER],
        "devices": {
            "trusted": devices.filter(trust_state=Device.Trust.TRUSTED).count(),
            "not_trusted": devices.exclude(trust_state=Device.Trust.TRUSTED).count(),
        },
        "unread_notifications": Notification.objects.filter(recipient=user, is_read=False).count(),
        "activity": _activity(user.organization, user, now),
    }


def organization_overview(user, now) -> dict:
    org = user.organization
    devices = Device.objects.filter(organization=org).exclude(trust_state=Device.Trust.REVOKED)
    open_alerts = AnomalyAlert.objects.filter(organization=org, status=AnomalyAlert.Status.OPEN)
    events = (
        AuditLog.objects.filter(organization=org)
        .filter(Q(action__in=SECURITY_EVENTS) | ~Q(outcome=AuditOutcome.SUCCESS))
        .order_by("-created_at", "-id")[:10]
    )
    return {
        "credentials": Credential.objects.filter(organization=org, archived_at__isnull=True).count(),
        "active_shares": _live_shares(now).filter(organization=org).count(),
        "pending_requests": AccessRequest.objects.filter(
            organization=org, status=AccessRequest.Status.PENDING, expires_at__gt=now
        ).count(),
        "devices": {
            "trusted": devices.filter(trust_state=Device.Trust.TRUSTED).count(),
            "pending": devices.filter(trust_state=Device.Trust.PENDING).count(),
            "suspended": devices.filter(trust_state=Device.Trust.SUSPENDED).count(),
        },
        "open_alerts": {
            severity: open_alerts.filter(severity=severity).count() for severity in AnomalyAlert.Severity.values
        },
        "active_lockdowns": [payload(s) for s in LockdownState.objects.filter(organization=org, is_active=True)],
        "recent_security_events": [
            {
                "created_at": e.created_at,
                "action": e.action,
                "outcome": e.outcome,
                "actor_email": e.actor_email,
                "target_label": e.target_label,
                "reason": e.reason,
            }
            for e in events
        ],
        "activity": _activity(org, None, now),
    }


class DashboardView(APIView):
    @extend_schema(
        responses={
            200: inline_serializer(
                "Dashboard", {"me": serializers.DictField(), "organization": serializers.DictField(allow_null=True)}
            )
        }
    )
    def get(self, request):
        now = timezone.now()
        overview = organization_overview(request.user, now) if has_perm(request.user, Perm.REPORTS_VIEW) else None
        return Response({"me": personal(request.user, now), "organization": overview})
