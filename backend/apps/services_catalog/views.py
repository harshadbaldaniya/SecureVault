from rest_framework import viewsets

from apps.audit.mixins import AuditedModelViewSetMixin
from core.permissions import Perm, requires
from core.tenancy import OrgScopedQuerysetMixin

from .models import ServiceCatalog
from .serializers import ServiceCatalogSerializer


class ServiceCatalogViewSet(AuditedModelViewSetMixin, OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    """Any active member can browse services; only ORG_ADMIN can change the catalog."""

    queryset = ServiceCatalog.objects.all()
    serializer_class = ServiceCatalogSerializer
    permission_classes = [requires(Perm.SERVICES_MANAGE, read_open=True)]
    audit_target_type = "service"
    filterset_fields = ["category", "status"]
    search_fields = ["name"]
    ordering_fields = ["name", "category", "created_at"]
