"""Append-only, hash-chained audit log.

Tamper evidence: each row stores SHA-256(canonical row content + previous row's hash),
per chain (one chain per organization, plus a "global" chain for events with no
organization, e.g. sign-in attempts for unknown emails). Editing, deleting or
re-ordering a row breaks every later hash, which `verify_chain` detects.

What this does NOT prove: someone with database-owner rights could rewrite the whole
chain consistently, or drop its tail. Defending against that needs hashes anchored
outside the database (signed checkpoints / external log shipping) - see docs.
"""

from django.db import models


class AuditAction(models.TextChoices):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    REVEAL = "REVEAL"
    COPY = "COPY"
    CREATE = "CREATE"
    EDIT = "EDIT"
    DELETE = "DELETE"
    SHARE = "SHARE"
    REVOKE = "REVOKE"
    INVITE = "INVITE"
    ACCOUNT_ACTIVATE = "ACCOUNT_ACTIVATE"
    KEY_ROTATION = "KEY_ROTATION"
    ANOMALY_REVIEW = "ANOMALY_REVIEW"
    MFA_ENROLL = "MFA_ENROLL"
    MFA_DISABLE = "MFA_DISABLE"
    MFA_RESET = "MFA_RESET"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET_REQUEST = "PASSWORD_RESET_REQUEST"
    PASSWORD_RESET = "PASSWORD_RESET"
    ACCESS_REQUEST = "ACCESS_REQUEST"
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    DEVICE_TRUST_CHANGE = "DEVICE_TRUST_CHANGE"
    LOCKDOWN = "LOCKDOWN"
    EMPLOYEE_IMPORT = "EMPLOYEE_IMPORT"
    POLICY_CHANGE = "POLICY_CHANGE"


class AuditOutcome(models.TextChoices):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit records are append-only.")

    def delete(self):
        raise PermissionError("Audit records are append-only.")


class AuditChainHead(models.Model):
    """Latest sequence/hash per chain. Locked (SELECT ... FOR UPDATE) while appending."""

    chain_key = models.CharField(max_length=64, primary_key=True)
    last_sequence = models.BigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, default="0" * 64)

    def __str__(self) -> str:
        return f"{self.chain_key}#{self.last_sequence}"


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    chain_key = models.CharField(max_length=64)
    sequence = models.BigIntegerField()
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField()
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, null=True, related_name="+"
    )
    # Actor is snapshotted (not a FK) so later user changes can never alter a hashed row.
    actor_id = models.UUIDField(null=True)
    actor_email = models.CharField(max_length=254, blank=True)

    action = models.CharField(max_length=32, choices=AuditAction.choices)
    outcome = models.CharField(max_length=16, choices=AuditOutcome.choices, default=AuditOutcome.SUCCESS)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_label = models.CharField(max_length=254, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict)

    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=36, blank=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["chain_key", "sequence"], name="audit_chain_sequence_unique"),
        ]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["organization", "action", "created_at"]),
            models.Index(fields=["organization", "actor_id", "created_at"]),
            models.Index(fields=["organization", "target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.chain_key}#{self.sequence} {self.action} {self.outcome}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit records are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit records are append-only.")
