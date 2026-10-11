from datetime import timedelta

from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel

PENDING_LIFETIME = timedelta(days=7)


class AccessRequest(TimeStampedModel):
    """A request for temporary access to a credential. Approval creates a time-bound share grant."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        CANCELLED = "CANCELLED"

    class Permission(models.TextChoices):
        VIEW = "VIEW"
        EDIT = "EDIT"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    credential = models.ForeignKey("vault.Credential", on_delete=models.CASCADE, related_name="access_requests")
    requester = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="access_requests")
    approver = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    permission = models.CharField(max_length=5, choices=Permission.choices, default=Permission.VIEW)
    requested_duration_hours = models.PositiveIntegerField()
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()  # a pending request lapses after this
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)
    share = models.ForeignKey("sharing.Share", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "requester"], condition=Q(status="PENDING"), name="one_pending_request_per_user"
            ),
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.requester_id} -> {self.credential_id} ({self.status})"

    def state(self, now) -> str:
        if self.status == self.Status.PENDING and self.expires_at <= now:
            return "EXPIRED"
        return self.status
