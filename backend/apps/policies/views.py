from django.db import transaction
from rest_framework import generics

from apps.audit import services as audit
from apps.audit.models import AuditAction
from core.permissions import Perm, requires

from .models import SecurityPolicy, policy_for
from .serializers import SecurityPolicySerializer


class SecurityPolicyView(generics.RetrieveUpdateAPIView):
    """GET: any active member (the UI needs the rules). PATCH: ORG_ADMIN or SEC_ADMIN, audited with a diff."""

    serializer_class = SecurityPolicySerializer
    permission_classes = [requires(Perm.POLICIES_MANAGE, read_open=True)]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return policy_for(self.request.user.organization)

    def perform_update(self, serializer):
        with transaction.atomic():
            # Lock the row so concurrent edits produce accurate before/after diffs.
            before = SecurityPolicy.objects.select_for_update().get(pk=serializer.instance.pk)
            policy = serializer.save()
            changes = {
                field: {"from": getattr(before, field), "to": getattr(policy, field)}
                for field in serializer.validated_data
                if getattr(before, field) != getattr(policy, field)
            }
            if changes:
                audit.record(AuditAction.POLICY_CHANGE, target=policy, target_type="security_policy",
                             metadata={"changes": changes})
