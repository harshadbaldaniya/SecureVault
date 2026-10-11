"""Operator break-glass: trust a device when no other administrator can (e.g. the sole admin after turning on
require_device_trust). Requires shell access to the server, is audited, and should be rare.

    manage.py approve_device --email admin@example.com              # list that user's devices
    manage.py approve_device --email admin@example.com --device <id> --reason "Bootstrap"
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.devices.models import Device, DeviceEvent


class Command(BaseCommand):
    help = "Trust a user's device from the server console (break-glass, audited)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--device", help="Device id to trust. Omit to list the user's devices.")
        parser.add_argument("--reason", default="Approved by operator from the server console")

    def handle(self, *args, email, device, reason, **options):
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError("No such user.") from None
        if not device:
            for d in Device.objects.filter(user=user).order_by("-created_at"):
                self.stdout.write(f"{d.pk}  {d.trust_state:<10} {d.name}  last seen {d.last_seen_at}")
            return
        try:
            target = Device.objects.get(pk=device, user=user)
        except (Device.DoesNotExist, ValueError):
            raise CommandError("No such device for that user.") from None
        if target.trust_state == Device.Trust.REVOKED:
            raise CommandError("Revoked devices cannot be trusted again; the browser must register anew.")
        with transaction.atomic():
            previous = target.trust_state
            target.trust_state = Device.Trust.TRUSTED
            target.trust_changed_at = timezone.now()
            target.trust_reason = reason[:300]
            target.save(update_fields=["trust_state", "trust_changed_at", "trust_reason", "updated_at"])
            DeviceEvent.objects.create(
                device=target,
                kind=DeviceEvent.Kind.TRUST_CHANGED,
                details={"from": previous, "to": "TRUSTED", "by": "operator-console"},
            )
            audit.record(
                AuditAction.DEVICE_TRUST_CHANGE,
                organization=user.organization,
                target=target,
                target_type="device",
                reason=reason[:300],
                metadata={"from": previous, "to": "TRUSTED", "via": "management_command"},
            )
        self.stdout.write(self.style.SUCCESS(f"Device {target.pk} is now TRUSTED."))
