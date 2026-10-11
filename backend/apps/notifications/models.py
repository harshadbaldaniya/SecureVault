import uuid

from django.db import models


class Notification(models.Model):
    """In-app alert for one user. Messages describe events; they never contain secrets."""

    class Type(models.TextChoices):
        INVITATION = "INVITATION"
        ACCESS_REQUEST = "ACCESS_REQUEST"
        ACCESS_APPROVED = "ACCESS_APPROVED"
        ACCESS_REJECTED = "ACCESS_REJECTED"
        SHARE_CREATED = "SHARE_CREATED"
        SHARE_EXPIRING = "SHARE_EXPIRING"
        SHARE_EXPIRED = "SHARE_EXPIRED"
        SHARE_REVOKED = "SHARE_REVOKED"
        DEVICE_TRUST_CHANGED = "DEVICE_TRUST_CHANGED"
        SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
        LOCKDOWN = "LOCKDOWN"
        IMPORT_COMPLETED = "IMPORT_COMPLETED"

    class Priority(models.TextChoices):
        LOW = "LOW"
        NORMAL = "NORMAL"
        HIGH = "HIGH"
        CRITICAL = "CRITICAL"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    recipient = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=32, choices=Type.choices)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=1000, blank=True)
    link = models.CharField(max_length=300, blank=True)  # in-app route, e.g. /vault
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "created_at"])]

    def __str__(self) -> str:
        return f"{self.type} -> {self.recipient_id}"
