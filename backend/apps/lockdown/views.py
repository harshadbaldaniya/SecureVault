from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from core.permissions import Perm, has_perm, requires
from core.tenancy import OrgScopedPrimaryKeyRelatedField

from . import services
from .models import LockdownState


class LockdownSerializer(serializers.ModelSerializer):
    target_user_name = serializers.CharField(source="target_user.full_name", read_only=True, default=None)
    initiated_by_name = serializers.CharField(source="initiated_by.full_name", read_only=True)
    resolved_by_name = serializers.CharField(source="resolved_by.full_name", read_only=True, default=None)
    triggered_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = LockdownState
        fields = [
            "id",
            "scope",
            "target_user",
            "target_user_name",
            "reason",
            "initiated_by_name",
            "triggered_at",
            "is_active",
            "terminated_session_count",
            "resolved_at",
            "resolved_by_name",
            "resolution_note",
        ]
        read_only_fields = fields


class ActivateSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=LockdownState.Scope.choices)
    target_user = OrgScopedPrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    reason = serializers.CharField(max_length=500)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    code = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)


class ResolveSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    code = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)


@method_decorator(sensitive_post_parameters("password", "code"), name="dispatch")
class LockdownViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Lockdown history and controls (security administrators). `status` is open to every member."""

    queryset = LockdownState.objects.none()
    serializer_class = LockdownSerializer
    filterset_fields = ["scope", "is_active"]
    lockdown_exempt = True  # administrators must be able to lift a lockdown that covers them

    def get_permissions(self):
        if self.action == "status":
            return super().get_permissions()
        return [requires(Perm.LOCKDOWN_MANAGE)()]

    def get_queryset(self):
        return LockdownState.objects.filter(organization=self.request.user.organization).select_related(
            "target_user", "initiated_by", "resolved_by"
        )

    @extend_schema(responses={200: LockdownSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def status(self, request):
        """Active lockdowns that apply to the caller (administrators see every active one)."""
        active = self.get_queryset().filter(is_active=True)
        if not has_perm(request.user, Perm.LOCKDOWN_MANAGE):
            state = services.applicable(request.user)
            active = active.filter(pk=state.pk) if state else active.none()
        return Response(LockdownSerializer(active, many=True).data)

    @extend_schema(request=ActivateSerializer, responses={201: LockdownSerializer})
    @action(detail=False, methods=["post"])
    def activate(self, request):
        body = ActivateSerializer(data=request.data, context={"request": request})
        body.is_valid(raise_exception=True)
        state = services.activate(actor=request.user, **body.validated_data)
        return Response(LockdownSerializer(state).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ResolveSerializer, responses={200: LockdownSerializer})
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        body = ResolveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        state = services.resolve(actor=request.user, state=self.get_object(), **body.validated_data)
        return Response(LockdownSerializer(state).data)
