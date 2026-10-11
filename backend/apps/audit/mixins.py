from django.db import transaction

from . import services
from .models import AuditAction


class AuditedModelViewSetMixin:
    """Wraps create/update/destroy in a transaction together with their audit record.

    Only changed field *names* are recorded, never values, so a future model with
    sensitive fields cannot leak them into the audit trail through this mixin.
    Place it before OrgScopedQuerysetMixin in the class bases.
    """

    audit_target_type: str = ""

    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)
            services.record(
                AuditAction.CREATE,
                target=serializer.instance,
                target_type=self.audit_target_type,
                metadata={"fields": sorted(serializer.validated_data)},
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            super().perform_update(serializer)
            services.record(
                AuditAction.EDIT,
                target=serializer.instance,
                target_type=self.audit_target_type,
                metadata={"changed": sorted(serializer.validated_data)},
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            target_id, label = str(instance.pk), str(instance)
            super().perform_destroy(instance)
            services.record(
                AuditAction.DELETE, target_type=self.audit_target_type, target_id=target_id, target_label=label
            )
