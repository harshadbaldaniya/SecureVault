from rest_framework import serializers

from apps.accounts.models import User
from core.tenancy import OrgScopedPrimaryKeyRelatedField

from .models import Department


class DepartmentSerializer(serializers.ModelSerializer):
    head = OrgScopedPrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True, required=False)
    head_name = serializers.CharField(source="head.full_name", read_only=True, default=None)
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "name", "code", "head", "head_name", "status", "employee_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_employee_count(self, department) -> int:
        # List/detail querysets annotate this; freshly created/updated objects fall back to a query.
        annotated = getattr(department, "employee_count", None)
        if annotated is not None:
            return annotated
        return department.users.filter(status="ACTIVE").count()

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        organization = self.context["request"].user.organization
        clash = Department.objects.filter(organization=organization, code=code)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A department with this code already exists.")
        return code
