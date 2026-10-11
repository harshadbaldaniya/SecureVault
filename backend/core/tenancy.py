"""Organization (tenant) isolation helpers.

Every tenant-owned queryset is filtered by the caller's organization, so an ID
from another organization behaves exactly like an ID that does not exist (404).
"""

from django.core.exceptions import ValidationError
from django.http import Http404
from rest_framework import serializers


def get_in_org_or_404(queryset, organization, pk):
    """Fetch one row of `organization` by primary key. Missing, malformed or foreign ids all become 404."""
    try:
        return queryset.get(pk=pk, organization=organization)
    except (queryset.model.DoesNotExist, ValueError, ValidationError):
        raise Http404 from None


class OrgScopedQuerysetMixin:
    """For ViewSets: scope reads to request.user.organization and stamp it on create."""

    def get_queryset(self):
        return super().get_queryset().filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A foreign-key field that only accepts objects from the caller's organization."""

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return queryset.none()
        return queryset.filter(organization=request.user.organization)
