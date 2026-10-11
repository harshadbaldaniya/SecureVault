from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from core.tenancy import OrgScopedPrimaryKeyRelatedField

from .models import Share


class PersonSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "department_name"]


class ShareSerializer(serializers.ModelSerializer):
    credential_title = serializers.CharField(source="credential.title", read_only=True)
    grantor = PersonSerializer(read_only=True)
    grantee = PersonSerializer(read_only=True)
    revoked_by_name = serializers.CharField(source="revoked_by.full_name", read_only=True, default=None)
    state = serializers.SerializerMethodField()

    class Meta:
        model = Share
        fields = [
            "id",
            "credential",
            "credential_title",
            "grantor",
            "grantee",
            "parent_share",
            "depth",
            "permission",
            "expires_at",
            "is_view_once",
            "burned_at",
            "revoked_at",
            "revoked_by_name",
            "revoke_reason",
            "state",
            "created_at",
        ]
        read_only_fields = fields

    def get_state(self, share) -> str:
        return share.state(timezone.now())


class ShareCreateSerializer(serializers.Serializer):
    grantee = OrgScopedPrimaryKeyRelatedField(queryset=User.objects.filter(status=User.Status.ACTIVE))
    permission = serializers.ChoiceField(choices=Share.Permission.choices, default=Share.Permission.VIEW)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    is_view_once = serializers.BooleanField(default=False)


class RevokeSerializer(serializers.Serializer):
    revoked = serializers.IntegerField()


class TreeNodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    parent_share = serializers.UUIDField(allow_null=True)
    depth = serializers.IntegerField()
    grantor = serializers.CharField()
    grantee = serializers.CharField()
    grantee_email = serializers.CharField()
    permission = serializers.CharField()
    state = serializers.CharField()
    expires_at = serializers.DateTimeField()
    is_view_once = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class DelegationTreeSerializer(serializers.Serializer):
    credential = serializers.UUIDField()
    credential_title = serializers.CharField()
    owner = serializers.CharField()
    nodes = TreeNodeSerializer(many=True)
