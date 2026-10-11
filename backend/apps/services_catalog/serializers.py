from rest_framework import serializers

from .models import ServiceCatalog


class ServiceCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCatalog
        fields = [
            "id", "name", "category", "base_url", "icon_url", "default_port", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value: str) -> str:
        name = value.strip()
        organization = self.context["request"].user.organization
        clash = ServiceCatalog.objects.filter(organization=organization, name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A service with this name already exists.")
        return name
