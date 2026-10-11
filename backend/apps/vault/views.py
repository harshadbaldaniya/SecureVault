from datetime import timedelta

import django_filters
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditOutcome
from apps.policies.models import policy_for
from apps.sharing import services as sharing_services
from apps.sharing.models import Share
from apps.sharing.serializers import ShareCreateSerializer, ShareSerializer
from core.http import no_store

from . import services
from .models import Credential, SecureNote
from .serializers import (
    CredentialSerializer,
    DirectoryEntrySerializer,
    RevealedCredentialSerializer,
    RevealedNoteSerializer,
    RevealRequestSerializer,
    SecureNoteSerializer,
)

_PROBE_ACTIONS = {
    "reveal": AuditAction.REVEAL,
    "update": AuditAction.EDIT,
    "partial_update": AuditAction.EDIT,
    "destroy": AuditAction.DELETE,
    "restore": AuditAction.EDIT,
}


class CredentialFilter(django_filters.FilterSet):
    tag = django_filters.CharFilter(method="filter_tag")
    expired = django_filters.BooleanFilter(method="filter_expired")
    expiring_within_days = django_filters.NumberFilter(method="filter_expiring")
    reused = django_filters.BooleanFilter(method="filter_reused")

    class Meta:
        model = Credential
        fields = ["service", "category", "secret_type"]

    def filter_tag(self, queryset, name, value):
        return queryset.filter(tags__contains=[value.strip().lower()])

    def filter_expired(self, queryset, name, value):
        expired = Q(expires_at__lt=timezone.localdate())
        return queryset.filter(expired) if value else queryset.exclude(expired)

    def filter_expiring(self, queryset, name, value):
        today = timezone.localdate()
        return queryset.filter(expires_at__gte=today, expires_at__lte=today + timedelta(days=int(value)))

    def filter_reused(self, queryset, name, value):
        return queryset.filter(reuse_count__gt=0) if value else queryset.filter(reuse_count=0)


class NoteFilter(django_filters.FilterSet):
    tag = django_filters.CharFilter(method="filter_tag")

    class Meta:
        model = SecureNote
        fields = ["category"]

    def filter_tag(self, queryset, name, value):
        return queryset.filter(tags__contains=[value.strip().lower()])


class VaultItemViewSet(viewsets.ModelViewSet):
    """Shared plumbing. Notes are visible to their owner only; credentials also to holders of a share grant.

    Search covers plaintext metadata only (title, username, service, tags, category).
    Secrets are never searchable.
    """

    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    ordering_fields = ["title", "created_at", "updated_at", "expires_at"]
    audit_kind = ""
    throttle_scope = None  # set per action (reveal) through @action(..., throttle_scope=...)

    def base_queryset(self):
        return self.queryset.model.objects.filter(organization=self.request.user.organization, owner=self.request.user)

    def get_queryset(self):
        queryset = self.base_queryset().select_related("owner")
        if self.action == "list":
            only_archived = self.request.query_params.get("archived", "").lower() in {"1", "true", "yes"}
            queryset = queryset.filter(archived_at__isnull=not only_archived)
        return queryset

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            self._audit_probe()
            raise

    def _audit_probe(self) -> None:
        """An item that exists in this organization but is not the caller's: record the attempt, still answer 404."""
        audit_action = _PROBE_ACTIONS.get(self.action)
        pk = self.kwargs.get("pk")
        if audit_action is None or pk is None:
            return
        try:
            exists = self.queryset.model.objects.filter(organization=self.request.user.organization, pk=pk).exists()
        except (DjangoValidationError, ValueError):
            return
        if exists:
            audit.record(
                audit_action,
                actor=self.request.user,
                outcome=AuditOutcome.DENIED,
                target_type=self.audit_kind,
                target_id=str(pk),
                reason="not_visible",
                fail_silently=True,
            )

    def destroy(self, request, *args, **kwargs):
        services.archive_item(user=request.user, item=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _restore(self, request):
        item = services.restore_item(user=request.user, item=self.get_object())
        return Response(self.get_serializer(item).data)

    def _reveal(self, request, field: str):
        item = self.get_object()
        request_serializer = RevealRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        secret = services.reveal(user=request.user, item=item, purpose=request_serializer.validated_data["purpose"])
        return no_store(Response({field: secret}))


class CredentialViewSet(VaultItemViewSet):
    queryset = Credential.objects.all()
    serializer_class = CredentialSerializer
    filterset_class = CredentialFilter
    search_fields = ["title", "username", "service__name", "category"]
    audit_kind = "credential"

    def base_queryset(self):
        """Own credentials, plus non-archived ones shared with the caller through an open grant.

        Grants that are live, or consumed view-once grants (so the reveal endpoint can answer 410 Gone).
        Exactly what the caller may DO is decided per request by core.access_gate (incl. the ancestor chain).
        """
        user = self.request.user
        shared = Share.objects.filter(grantee=user, revoked_at__isnull=True).filter(
            Q(burned_at__isnull=False) | Q(expires_at__gt=timezone.now())
        )
        visible = Q(owner=user) | (Q(pk__in=shared.values("credential_id")) & Q(archived_at__isnull=True))
        queryset = Credential.objects.filter(organization=user.organization).filter(visible)
        scope = self.request.query_params.get("scope") if self.action == "list" else None
        if scope == "mine":
            queryset = queryset.filter(owner=user)
        elif scope == "shared":
            queryset = queryset.exclude(owner=user)
        return queryset

    def get_queryset(self):
        # reuse_count: other ACTIVE credentials of the same owner with the same blind index. Computed in
        # SQL from the keyed hashes, without decrypting anything.
        same_secret = (
            Credential.objects.filter(
                organization=OuterRef("organization"),
                owner=OuterRef("owner"),
                blind_index=OuterRef("blind_index"),
                blind_index_version=OuterRef("blind_index_version"),
                archived_at__isnull=True,
            )
            .exclude(pk=OuterRef("pk"))
            .values("owner")
            .annotate(total=Count("pk"))
            .values("total")
        )
        return (
            super()
            .get_queryset()
            .select_related("service")
            .annotate(reuse_count=Coalesce(Subquery(same_secret, output_field=IntegerField()), 0))
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self.request, "user", None) and self.request.user.is_authenticated:
            context["expiry_warning_days"] = policy_for(self.request.user.organization).expiry_warning_days
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential = services.create_credential(user=request.user, **serializer.validated_data)
        return Response(self.get_serializer(self.get_queryset().get(pk=credential.pk)).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        credential = self.get_object()
        serializer = self.get_serializer(credential, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_credential(user=request.user, credential=credential, **serializer.validated_data)
        return Response(self.get_serializer(self.get_queryset().get(pk=credential.pk)).data)

    @extend_schema(request=None, responses={200: CredentialSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._restore(request)

    @extend_schema(request=RevealRequestSerializer, responses={200: RevealedCredentialSerializer})
    @action(
        detail=True, methods=["post"], throttle_classes=[ScopedRateThrottle, UserRateThrottle], throttle_scope="reveal"
    )
    def reveal(self, request, pk=None):
        return self._reveal(request, "password")

    @extend_schema(request=ShareCreateSerializer, responses={201: ShareSerializer})
    @action(detail=True, methods=["post"])
    def share(self, request, pk=None):
        credential = self.get_object()
        serializer = ShareCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        share = sharing_services.create_share(actor=request.user, credential=credential, **serializer.validated_data)
        return Response(ShareSerializer(share).data, status=status.HTTP_201_CREATED)


class CredentialDirectoryView(generics.ListAPIView):
    """Credentials whose owners opted in to access requests. Metadata only: no username, no secret."""

    queryset = Credential.objects.none()  # for schema generation; get_queryset() scopes to the caller
    serializer_class = DirectoryEntrySerializer
    search_fields = ["title", "service__name", "category", "owner__full_name"]

    def get_queryset(self):
        user = self.request.user
        return (
            Credential.objects.filter(organization=user.organization, requestable=True, archived_at__isnull=True)
            .exclude(owner=user)
            .select_related("service", "owner")
            .order_by("title", "id")
        )


class NoteViewSet(VaultItemViewSet):
    queryset = SecureNote.objects.all()
    serializer_class = SecureNoteSerializer
    filterset_class = NoteFilter
    search_fields = ["title", "category"]
    audit_kind = "note"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = services.create_note(user=request.user, **serializer.validated_data)
        return Response(self.get_serializer(note).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        note = self.get_object()
        serializer = self.get_serializer(note, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_note(user=request.user, note=note, **serializer.validated_data)
        return Response(self.get_serializer(updated).data)

    @extend_schema(request=None, responses={200: SecureNoteSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._restore(request)

    @extend_schema(request=RevealRequestSerializer, responses={200: RevealedNoteSerializer})
    @action(
        detail=True, methods=["post"], throttle_classes=[ScopedRateThrottle, UserRateThrottle], throttle_scope="reveal"
    )
    def reveal(self, request, pk=None):
        return self._reveal(request, "content")
