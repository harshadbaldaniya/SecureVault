from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "sequence",
            "created_at",
            "action",
            "outcome",
            "actor_id",
            "actor_email",
            "target_type",
            "target_id",
            "target_label",
            "reason",
            "metadata",
            "ip_address",
            "user_agent",
            "request_id",
            "prev_hash",
            "hash",
        ]
        read_only_fields = fields


class ChainVerificationSerializer(serializers.Serializer):
    chain = serializers.CharField()
    valid = serializers.BooleanField()
    checked = serializers.IntegerField()
    broken_at_sequence = serializers.IntegerField(allow_null=True)
