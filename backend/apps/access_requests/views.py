from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.vault.models import Credential
from core.tenancy import OrgScopedPrimaryKeyRelatedField

from . import services
from .models import AccessRequest


class AccessRequestSerializer(serializers.ModelSerializer):
    credential_title = serializers.CharField(source="credential.title", read_only=True)
    requester_name = serializers.CharField(source="requester.full_name", read_only=True)
    owner_name = serializers.CharField(source="credential.owner.full_name", read_only=True)
    approver_name = serializers.CharField(source="approver.full_name", read_only=True, default=None)
    state = serializers.SerializerMethodField()

    class Meta:
        model = AccessRequest
        fields = [
            "id",
            "credential",
            "credential_title",
            "owner_name",
            "requester_name",
            "approver_name",
            "permission",
            "requested_duration_hours",
            "reason",
            "state",
            "expires_at",
            "decided_at",
            "decision_note",
            "share",
            "created_at",
        ]
        read_only_fields = fields

    def get_state(self, request) -> str:
        return request.state(timezone.now())


class AccessRequestCreateSerializer(serializers.Serializer):
    credential = OrgScopedPrimaryKeyRelatedField(queryset=Credential.objects.all())
    permission = serializers.ChoiceField(choices=AccessRequest.Permission.choices, default="VIEW")
    duration_hours = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=5, max_length=500)


class DecisionSerializer(serializers.Serializer):
    duration_hours = serializers.IntegerField(min_value=1, required=False)
    permission = serializers.ChoiceField(choices=AccessRequest.Permission.choices, required=False)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class AccessRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Requests you made (box=mine) or that await your decision as a credential owner (box=to_approve)."""

    queryset = AccessRequest.objects.none()  # for schema generation; get_queryset() scopes to the caller
    serializer_class = AccessRequestSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = AccessRequest.objects.filter(organization=user.organization).select_related(
            "credential__owner", "requester", "approver"
        )
        box = self.request.query_params.get("box")
        if box == "mine":
            return queryset.filter(requester=user)
        if box == "to_approve":
            return queryset.filter(credential__owner=user)
        return queryset.filter(Q(requester=user) | Q(credential__owner=user))

    @extend_schema(parameters=[OpenApiParameter("box", str, enum=["mine", "to_approve"])])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=AccessRequestCreateSerializer, responses={201: AccessRequestSerializer})
    def create(self, request):
        serializer = AccessRequestCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        created = services.create_request(requester=request.user, **serializer.validated_data)
        return Response(AccessRequestSerializer(created).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DecisionSerializer, responses={200: AccessRequestSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        decided = services.approve(
            approver=request.user,
            request=self.get_object(),
            duration_hours=data.get("duration_hours"),
            permission=data.get("permission"),
        )
        return Response(AccessRequestSerializer(decided).data)

    @extend_schema(request=DecisionSerializer, responses={200: AccessRequestSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decided = services.reject(
            approver=request.user, request=self.get_object(), note=serializer.validated_data.get("note", "")
        )
        return Response(AccessRequestSerializer(decided).data)

    @extend_schema(request=None, responses={200: AccessRequestSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(
            AccessRequestSerializer(services.cancel(requester=request.user, request=self.get_object())).data
        )
