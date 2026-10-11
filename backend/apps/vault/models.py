from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from core.access_gate import Action
from core.models import TimeStampedModel

ALL_ACTIONS = frozenset(Action)


class OrganizationKey(TimeStampedModel):
    """A per-organization data key (DEK), stored only in wrapped (encrypted) form.

    The KEK that wraps it lives outside the database (see apps.vault.keys). Rotating the DEK
    creates a new version; older versions stay RETIRED but readable until every record has
    been re-encrypted and backups that depend on them have aged out.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="vault_keys")
    version = models.PositiveIntegerField()
    wrapped_key = models.TextField()
    kek_version = models.PositiveIntegerField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["organization", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "version"], name="vault_key_org_version_unique"),
            models.UniqueConstraint(
                fields=["organization"], condition=Q(status="ACTIVE"), name="vault_one_active_key_per_org"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} key v{self.version} ({self.status})"


class VaultItem(TimeStampedModel):
    """Shared shape of everything stored encrypted in the vault.

    Titles, categories, tags and expiry are plaintext *metadata* (searchable, reportable).
    The secret itself exists only as `secret_ciphertext`.
    """

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="+")
    owner = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=40, blank=True)
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    expires_at = models.DateField(null=True, blank=True)

    # AES-256-GCM token "v<dek version>:<nonce>:<ciphertext+tag>" (see core.crypto)
    secret_ciphertext = models.TextField()
    key_version = models.PositiveIntegerField()

    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.title

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def permissions_for(self, user) -> frozenset[Action]:
        """What `user` may do with this item. Phase 2: only the owner. Phase 3 adds share grants.

        Roles never appear here: being an administrator does not grant access to a secret.
        """
        if user.organization_id != self.organization_id:
            return frozenset()
        if self.owner_id == user.id:
            return ALL_ACTIONS
        return frozenset()


class Credential(VaultItem):
    class SecretType(models.TextChoices):
        PASSWORD = "PASSWORD", "Password"
        API_KEY = "API_KEY", "API key / token"
        OTHER = "OTHER", "Other secret"

    service = models.ForeignKey(
        "services_catalog.ServiceCatalog", on_delete=models.PROTECT, null=True, blank=True, related_name="credentials"
    )
    username = models.CharField(max_length=254, blank=True)
    secret_type = models.CharField(max_length=10, choices=SecretType.choices, default=SecretType.PASSWORD)

    # Reuse analysis only: HMAC-SHA-256 under a key that is separate from the encryption keys.
    # Deterministic by design, so it reveals which credentials share a secret (equality/frequency).
    blind_index = models.CharField(max_length=64, blank=True)
    blind_index_version = models.PositiveSmallIntegerField(default=0)

    entropy_bits = models.FloatField(default=0)
    password_changed_at = models.DateTimeField()

    class Meta:
        ordering = ["title", "id"]
        indexes = [
            models.Index(fields=["organization", "owner", "archived_at"]),
            models.Index(fields=["organization", "blind_index"]),
            models.Index(fields=["organization", "expires_at"]),
            GinIndex(fields=["tags"], name="vault_credential_tags_gin"),
        ]


class SecureNote(VaultItem):
    class Meta:
        ordering = ["title", "id"]
        indexes = [
            models.Index(fields=["organization", "owner", "archived_at"]),
            GinIndex(fields=["tags"], name="vault_note_tags_gin"),
        ]
