from django.db import models

from core.models import TimeStampedModel


class Device(TimeStampedModel):
    """A browser/machine a user signs in from.

    Identity comes from a random server-issued token kept in an HttpOnly cookie (only its SHA-256 hash is
    stored). The client-reported fingerprint is a RISK SIGNAL only: it can be spoofed or change, so a mismatch
    raises an alert but never grants or proves anything.
    """

    class Trust(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        TRUSTED = "TRUSTED", "Trusted"
        SUSPENDED = "SUSPENDED", "Suspended"
        REVOKED = "REVOKED", "Revoked"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)
    fingerprint_hash = models.CharField(max_length=64, blank=True)
    os = models.CharField(max_length=40, blank=True)
    browser = models.CharField(max_length=40, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    trust_state = models.CharField(max_length=10, choices=Trust.choices, default=Trust.PENDING)
    first_ip = models.GenericIPAddressField(null=True, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    trust_changed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    trust_changed_at = models.DateTimeField(null=True, blank=True)
    trust_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "trust_state"]),
            models.Index(fields=["user", "last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.trust_state})"


class DeviceEvent(models.Model):
    """Device activity history."""

    class Kind(models.TextChoices):
        REGISTERED = "REGISTERED"
        SEEN = "SEEN"
        SENSITIVE_ACTION = "SENSITIVE_ACTION"
        TRUST_CHANGED = "TRUST_CHANGED"
        FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH"
        BLOCKED = "BLOCKED"

    id = models.BigAutoField(primary_key=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["device", "created_at"])]

    def __str__(self) -> str:
        return f"{self.kind} on {self.device_id}"


class AnomalyAlert(TimeStampedModel):
    """A reviewable alert raised by a transparent, rule-based detector (no machine learning)."""

    class Type(models.TextChoices):
        NEW_DEVICE = "NEW_DEVICE", "Sign-in from a new device"
        NEW_NETWORK = "NEW_NETWORK", "Sign-in from an unfamiliar network"
        UNTRUSTED_DEVICE = "UNTRUSTED_DEVICE", "Sensitive action blocked on an untrusted device"
        REVEAL_BURST = "REVEAL_BURST", "Unusually many secrets revealed"
        FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH", "Device signals changed"

    class Severity(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"

    class Status(models.TextChoices):
        OPEN = "OPEN"
        ACKNOWLEDGED = "ACKNOWLEDGED"
        DISMISSED = "DISMISSED"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="anomaly_alerts")
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts")
    type = models.CharField(max_length=24, choices=Type.choices)
    severity = models.CharField(max_length=6, choices=Severity.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    summary = models.CharField(max_length=300)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    reviewed_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
            models.Index(fields=["user", "type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} ({self.severity}) for {self.user_id}"
