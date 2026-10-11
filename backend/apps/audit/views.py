import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import Perm, requires
from core.tenancy import OrgScopedQuerysetMixin

from . import services
from .models import AuditAction, AuditLog, AuditOutcome
from .serializers import AuditLogSerializer, ChainVerificationSerializer


class AuditLogFilter(django_filters.FilterSet):
    action = django_filters.MultipleChoiceFilter(choices=AuditAction.choices)
    outcome = django_filters.ChoiceFilter(choices=AuditOutcome.choices)
    created_after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = AuditLog
        fields = ["action", "outcome", "actor_id", "target_type", "target_id", "request_id"]


class AuditLogViewSet(
    OrgScopedQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Read-only audit trail. There is deliberately no create/update/delete endpoint."""

    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [requires(Perm.AUDIT_VIEW)]
    filterset_class = AuditLogFilter
    search_fields = ["actor_email", "target_label"]
    ordering_fields = ["created_at", "sequence"]

    @extend_schema(responses={200: ChainVerificationSerializer})
    @action(detail=False, methods=["get"])
    def verify(self, request):
        result = services.verify_chain(services.chain_key_for(request.user.organization))
        return Response(ChainVerificationSerializer(result).data)
