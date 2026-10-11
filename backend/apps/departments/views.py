from django.db.models import Count, Q
from rest_framework import viewsets

from core.permissions import Perm, requires
from core.tenancy import OrgScopedQuerysetMixin

from .models import Department
from .serializers import DepartmentSerializer


class DepartmentViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    """Any active member can list departments; only ORG_ADMIN can change them."""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [requires(Perm.DEPARTMENTS_MANAGE, read_open=True)]
    filterset_fields = ["status"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("head")
            .annotate(employee_count=Count("users", filter=Q(users__status="ACTIVE")))
            .order_by("name")  # aggregate queries drop Meta.ordering; keep pagination stable
        )
