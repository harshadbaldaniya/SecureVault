from django.db import models
from django.db.models import F, Q

from core.models import TimeStampedModel

MAX_DELEGATION_DEPTH = 5


class Share(TimeStampedModel):
    """A grant of access to one credential: grantor -> grantee, optionally delegated from a parent grant.

    Grants form a tree per credential (parent_share). A grant is usable only while it and every ancestor are
    live: not revoked, not consumed (view-once), not expired. Revoking a grant revokes its whole subtree in the
    same transaction; access checks additionally walk the ancestor chain as defense in depth.
    """

    class Permission(models.TextChoices):
        VIEW = "VIEW", "View (reveal and copy)"
        EDIT = "EDIT", "Edit"
        SHARE = "SHARE", "Share (delegate further)"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    credential = models.ForeignKey("vault.Credential", on_delete=models.CASCADE, related_name="shares")
    grantor = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="shares_given")
    grantee = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="shares_received")
    parent_share = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    depth = models.PositiveSmallIntegerField(default=0)

    permission = models.CharField(max_length=5, choices=Permission.choices, default=Permission.VIEW)
    expires_at = models.DateTimeField()
    is_view_once = models.BooleanField(default=False)
    burned_at = models.DateTimeField(null=True, blank=True)  # set atomically on the single allowed view-once reveal

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    revoke_reason = models.CharField(max_length=32, blank=True)

    expiring_notified_at = models.DateTimeField(null=True, blank=True)
    expired_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(grantor=F("grantee")), name="share_not_to_self"),
            models.CheckConstraint(
                condition=Q(is_view_once=False) | Q(permission="VIEW"), name="share_view_once_is_view_only"
            ),
            models.CheckConstraint(condition=Q(depth__lte=MAX_DELEGATION_DEPTH), name="share_depth_limit"),
            models.CheckConstraint(
                condition=Q(parent_share__isnull=True, depth=0) | Q(parent_share__isnull=False, depth__gt=0),
                name="share_depth_matches_parent",
            ),
            models.UniqueConstraint(
                fields=["credential", "grantor", "grantee"],
                condition=Q(revoked_at__isnull=True, burned_at__isnull=True),
                name="share_one_open_grant_per_pair",
            ),
        ]
        indexes = [
            models.Index(fields=["grantee", "credential", "revoked_at"]),
            models.Index(fields=["credential", "parent_share"]),
            models.Index(fields=["organization", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.permission} {self.credential_id}: {self.grantor_id} -> {self.grantee_id}"

    def state(self, now) -> str:
        if self.revoked_at:
            return "REVOKED"
        if self.burned_at:
            return "CONSUMED"
        if self.expires_at <= now:
            return "EXPIRED"
        return "ACTIVE"
