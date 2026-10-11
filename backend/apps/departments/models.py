from django.db import models

from core.models import TimeStampedModel


class Department(TimeStampedModel):
    """Organizational unit and access boundary. Employee count is computed, never stored."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="departments"
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20)
    head = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="headed_departments"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="departments_org_code_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
