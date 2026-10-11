from django.db import models

from core.models import TimeStampedModel


class ImportJob(TimeStampedModel):
    """One spreadsheet upload. The file itself is never stored; only the parsed rows still waiting to be
    processed (cleared when the job finishes) and row-level results."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"  # the file as a whole was unusable (wrong format, missing columns ...)

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    uploaded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    file_name = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    # [{"row": 7, "email": "...", "full_name": "...", "department": "...", "role": "...",
    #   "errors": [{"field": "email", "message": "..."}]}]
    errors = models.JSONField(default=list, blank=True)
    file_error = models.CharField(max_length=500, blank=True)
    pending_rows = models.JSONField(default=list, blank=True)  # cleared after processing
    retry_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="retries")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "created_at"]), models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.status})"
