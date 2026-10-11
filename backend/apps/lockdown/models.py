from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel


class LockdownState(TimeStampedModel):
    """Emergency freeze register. While active, the server refuses every sensitive action in scope.

    GLOBAL: the whole organization. Administrators keep their sessions to manage the incident, but they too
    cannot reveal, copy, edit or share secrets. USER: one person.
    """

    class Scope(models.TextChoices):
        GLOBAL = "GLOBAL", "Organization-wide"
        USER = "USER", "One user"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    scope = models.CharField(max_length=6, choices=Scope.choices)
    target_user = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    reason = models.CharField(max_length=500)
    initiated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)
    terminated_session_count = models.PositiveIntegerField(default=0)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(scope="GLOBAL", target_user__isnull=True) | Q(scope="USER", target_user__isnull=False)),
                name="lockdown_target_matches_scope",
            ),
            models.UniqueConstraint(
                fields=["organization"], condition=Q(is_active=True, scope="GLOBAL"), name="one_active_global_lockdown"
            ),
            models.UniqueConstraint(
                fields=["organization", "target_user"],
                condition=Q(is_active=True, scope="USER"),
                name="one_active_lockdown_per_user",
            ),
        ]
        indexes = [models.Index(fields=["organization", "is_active"])]

    def __str__(self) -> str:
        return f"{self.scope} lockdown ({'active' if self.is_active else 'resolved'})"

    @property
    def triggered_at(self):
        return self.created_at
