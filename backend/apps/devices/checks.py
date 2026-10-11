"""Zero-trust gate checks contributed by this app (see core.access_gate.register_check)."""

from rest_framework import exceptions

from apps.policies.models import policy_for
from core import request_context
from core.access_gate import GateContext

from . import anomaly
from .models import AnomalyAlert, Device, DeviceEvent
from .services import device_from_request


def device_trust_check(ctx: GateContext) -> None:
    """Pipeline step 6. With require_device_trust on, sensitive actions need this user's TRUSTED device."""
    req = request_context.current()
    device = device_from_request(req.request) if req else None
    ip = req.ip_address if req else None
    if not policy_for(ctx.user.organization).require_device_trust:
        if device is not None:
            DeviceEvent.objects.create(
                device=device, kind=DeviceEvent.Kind.SENSITIVE_ACTION, ip_address=ip, details={"action": ctx.action}
            )
        return
    if device is None or device.trust_state != Device.Trust.TRUSTED:
        state = device.trust_state if device else "UNREGISTERED"
        if device is not None:
            DeviceEvent.objects.create(
                device=device,
                kind=DeviceEvent.Kind.BLOCKED,
                ip_address=ip,
                details={"action": ctx.action, "state": state},
            )
        anomaly.raise_alert(
            user=ctx.user,
            type=AnomalyAlert.Type.UNTRUSTED_DEVICE,
            severity=AnomalyAlert.Severity.MEDIUM,
            summary=f"Blocked {ctx.action.lower()} by {ctx.user.full_name} from a {state.lower()} device.",
            details={"action": ctx.action, "device_state": state},
            device=device,
            ip=ip,
        )
        raise exceptions.PermissionDenied(
            "This device is not trusted for sensitive actions. Ask a security administrator to approve it.",
            code="device_untrusted",
        )
    DeviceEvent.objects.create(
        device=device, kind=DeviceEvent.Kind.SENSITIVE_ACTION, ip_address=ip, details={"action": ctx.action}
    )


def anomaly_hold_check(ctx: GateContext) -> None:
    """Pipeline step 7. Optional policy: an open HIGH-severity alert holds the user's sensitive actions."""
    if not policy_for(ctx.user.organization).block_on_high_risk:
        return
    if AnomalyAlert.objects.filter(
        user=ctx.user, severity=AnomalyAlert.Severity.HIGH, status=AnomalyAlert.Status.OPEN
    ).exists():
        raise exceptions.PermissionDenied(
            "Sensitive actions are paused while a security alert on your account is reviewed.", code="risk_hold"
        )
