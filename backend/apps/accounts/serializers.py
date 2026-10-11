from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from apps.departments.models import Department
from apps.organizations.models import Organization
from core.permissions import permissions_for
from core.tenancy import OrgScopedPrimaryKeyRelatedField

from . import mfa
from .models import Invitation, User


class OrganizationBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug"]


class DepartmentBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "code"]


class MeSerializer(serializers.ModelSerializer):
    organization = OrganizationBriefSerializer(read_only=True)
    department = DepartmentBriefSerializer(read_only=True, allow_null=True)
    permissions = serializers.SerializerMethodField()
    mfa_enabled = serializers.SerializerMethodField()
    mfa_enrollment_required = serializers.SerializerMethodField()
    lockdown = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "status",
            "organization",
            "department",
            "permissions",
            "mfa_enabled",
            "mfa_enrollment_required",
            "lockdown",
        ]

    @extend_schema_field(
        inline_serializer(
            "ActiveLockdown",
            {
                "id": serializers.UUIDField(),
                "scope": serializers.CharField(),
                "target_user_id": serializers.UUIDField(allow_null=True),
                "triggered_at": serializers.DateTimeField(),
                "is_active": serializers.BooleanField(),
            },
            allow_null=True,
        )
    )
    def get_lockdown(self, user):
        from apps.lockdown.services import applicable, payload  # local: lockdown builds on accounts

        return payload(applicable(user))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, user):
        # For UI only (showing/hiding controls). The server re-checks every request.
        return sorted(permissions_for(user))

    def get_mfa_enabled(self, user) -> bool:
        return mfa.has_confirmed_totp(user)

    def get_mfa_enrollment_required(self, user) -> bool:
        return mfa.enrollment_required(user)


class LoginResultSerializer(serializers.Serializer):
    """`user` is null while a second factor is still required."""

    mfa_required = serializers.BooleanField()
    user = MeSerializer(allow_null=True)


class MfaCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, write_only=True)


class ReauthSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    code = serializers.CharField(max_length=32, write_only=True)


class TotpSetupSerializer(serializers.Serializer):
    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()


class RecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128, write_only=True)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class ResetLinkSerializer(serializers.Serializer):
    reset_url = serializers.CharField()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128, write_only=True)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class UserAdminSerializer(serializers.ModelSerializer):
    department = OrgScopedPrimaryKeyRelatedField(queryset=Department.objects.all(), allow_null=True, required=False)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "status",
            "department",
            "department_name",
            "last_login",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "last_login", "created_at", "updated_at"]


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    full_name = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=User.Role.choices, default=User.Role.EMPLOYEE)
    department = OrgScopedPrimaryKeyRelatedField(queryset=Department.objects.all(), allow_null=True, required=False)


class InvitationSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    role = serializers.CharField(source="user.role", read_only=True)
    invited_by_name = serializers.CharField(source="invited_by.full_name", read_only=True, default=None)
    state = serializers.CharField(read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "state",
            "invited_by_name",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "created_at",
        ]


class InvitationLinkSerializer(InvitationSerializer):
    """Returned only by create/resend: includes the one-time activation link."""

    invite_url = serializers.CharField(read_only=True)

    class Meta(InvitationSerializer.Meta):
        fields = [*InvitationSerializer.Meta.fields, "invite_url"]


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()
