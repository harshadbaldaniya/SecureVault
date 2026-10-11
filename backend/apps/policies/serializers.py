from rest_framework import serializers

from .models import SecurityPolicy


class SecurityPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityPolicy
        fields = [
            "id",
            "name",
            "min_password_length",
            "require_uppercase",
            "require_numbers",
            "require_symbols",
            "max_password_age_days",
            "expiry_warning_days",
            "allow_view_once",
            "max_share_duration_days",
            "require_device_trust",
            "require_mfa",
            "block_on_high_risk",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]
