import re

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from apps.services_catalog.models import ServiceCatalog
from core.tenancy import OrgScopedPrimaryKeyRelatedField

from .models import Credential, SecureNote
from .strength import strength_label

MAX_SECRET_LENGTH = 4096
MAX_NOTE_LENGTH = 65_536
MAX_TAGS = 20
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 ._-]{0,39}$")


class TagListField(serializers.ListField):
    """Lower-cased, de-duplicated tags: short labels made of letters, digits, space, dot, dash, underscore."""

    child = serializers.CharField(max_length=40)

    def to_internal_value(self, data):
        tags = super().to_internal_value(data)
        cleaned: list[str] = []
        for tag in tags:
            tag = tag.strip().lower()
            if not _TAG_PATTERN.match(tag):
                raise serializers.ValidationError(
                    "Tags may use letters, numbers, spaces, dots, dashes and underscores (max 40 characters)."
                )
            if tag not in cleaned:
                cleaned.append(tag)
        if len(cleaned) > MAX_TAGS:
            raise serializers.ValidationError(f"Use at most {MAX_TAGS} tags.")
        return cleaned


def _validate_expiry(value):
    if value is not None and value < timezone.localdate():
        raise serializers.ValidationError("The expiry date cannot be in the past.")
    return value


class VaultItemSerializer(serializers.ModelSerializer):
    """Common behaviour. Secrets are write-only: no read serializer ever contains one."""

    tags = TagListField(required=False)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    permissions = serializers.SerializerMethodField()

    secret_field = ""  # name of the write-only secret input, set by subclasses

    def validate_expires_at(self, value):
        # Only reject a *changed* past date, so editing an already-expired item's title still works.
        if self.instance is not None and value == self.instance.expires_at:
            return value
        return _validate_expiry(value)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, item) -> list[str]:
        # UI hints only; the server re-checks every action through core.access_gate.
        return sorted(item.permissions_for(self.context["request"].user))

    def validate(self, attrs):
        if self.instance is None and not attrs.get(self.secret_field):
            raise serializers.ValidationError({self.secret_field: "This field is required."})
        return attrs


class CredentialSerializer(VaultItemSerializer):
    secret_field = "password"  # noqa: S105 - field name, not a secret

    password = serializers.CharField(
        write_only=True, required=False, trim_whitespace=False, max_length=MAX_SECRET_LENGTH, allow_blank=False
    )
    service = OrgScopedPrimaryKeyRelatedField(
        queryset=ServiceCatalog.objects.filter(status=ServiceCatalog.Status.ACTIVE), allow_null=True, required=False
    )
    service_name = serializers.CharField(source="service.name", read_only=True, default=None)
    strength = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    expires_soon = serializers.SerializerMethodField()
    password_age_days = serializers.SerializerMethodField()
    reuse_count = serializers.SerializerMethodField()
    access = serializers.SerializerMethodField()
    sharing = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = [
            "id", "title", "username", "service", "service_name", "secret_type", "category", "tags", "expires_at",
            "password", "entropy_bits", "strength", "is_expired", "expires_soon", "password_age_days", "reuse_count",
            "owner_name", "permissions", "access", "sharing", "requestable", "archived_at", "created_at", "updated_at",
            "password_changed_at",
        ]
        read_only_fields = ["id", "entropy_bits", "archived_at", "created_at", "updated_at", "password_changed_at"]

    def _viewer(self):
        return self.context["request"].user

    def get_access(self, credential) -> str:
        return "owner" if credential.owner_id == self._viewer().id else "shared"

    @extend_schema_field(
        inline_serializer(
            "CredentialSharing",
            {
                "permission": serializers.CharField(allow_null=True),
                "expires_at": serializers.DateTimeField(allow_null=True),
                "shared_by": serializers.CharField(allow_null=True),
                "view_once": serializers.BooleanField(),
                "consumed": serializers.BooleanField(),
            },
            allow_null=True,
        )
    )
    def get_sharing(self, credential):
        """For grantees: how they got access. Null for the owner."""
        viewer = self._viewer()
        if credential.owner_id == viewer.id:
            return None
        access = credential.access_for(viewer)
        share = access.share
        return {
            "permission": share.permission if share else None,
            "expires_at": share.expires_at if share else None,
            "shared_by": share.grantor.full_name if share else None,
            "view_once": bool(share and share.is_view_once),
            "consumed": access.consumed,
        }

    def get_strength(self, credential) -> str:
        return strength_label(credential.entropy_bits)

    def get_is_expired(self, credential) -> bool:
        return credential.expires_at is not None and credential.expires_at < timezone.localdate()

    def get_expires_soon(self, credential) -> bool:
        if credential.expires_at is None or self.get_is_expired(credential):
            return False
        warning_days = self.context.get("expiry_warning_days", 14)
        return (credential.expires_at - timezone.localdate()).days <= warning_days

    def get_password_age_days(self, credential) -> int:
        return (timezone.now() - credential.password_changed_at).days

    def get_reuse_count(self, credential) -> int:
        """How many of *your other* active credentials share this password (annotated by the viewset).
        Always 0 for credentials shared with you: the owner's reuse habits are not the grantee's business."""
        if credential.owner_id != self._viewer().id:
            return 0
        return getattr(credential, "reuse_count", 0) or 0


class SecureNoteSerializer(VaultItemSerializer):
    secret_field = "content"  # noqa: S105 - field name, not a secret

    content = serializers.CharField(
        write_only=True, required=False, trim_whitespace=False, max_length=MAX_NOTE_LENGTH, allow_blank=False
    )

    class Meta:
        model = SecureNote
        fields = [
            "id", "title", "category", "tags", "expires_at", "content", "owner_name", "permissions",
            "archived_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "archived_at", "created_at", "updated_at"]


class DirectoryEntrySerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True, default=None)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = Credential
        fields = ["id", "title", "service_name", "category", "owner_name"]
        read_only_fields = fields


class RevealRequestSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=["view", "copy"], default="view")


class RevealedCredentialSerializer(serializers.Serializer):
    password = serializers.CharField()


class RevealedNoteSerializer(serializers.Serializer):
    content = serializers.CharField()
