from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from core.permissions import Perm, has_perm, requires

from . import services
from .models import AnomalyAlert, Device, DeviceEvent


class DeviceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    trust_changed_by_name = serializers.CharField(source="trust_changed_by.full_name", read_only=True, default=None)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            "id",
            "name",
            "user",
            "user_name",
            "user_email",
            "os",
            "browser",
            "trust_state",
            "first_ip",
            "last_ip",
            "last_seen_at",
            "trust_changed_by_name",
            "trust_changed_at",
            "trust_reason",
            "is_current",
            "created_at",
        ]
        read_only_fields = [f for f in fields if f != "name"]

    def get_is_current(self, device) -> bool:
        current = services.device_from_request(self.context.get("request"))
        return current is not None and current.pk == device.pk


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    # Hex SHA-256 of client-side signals (a risk signal only; never trusted on its own).
    fingerprint = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class TrustChangeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class DeviceEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceEvent
        fields = ["id", "kind", "ip_address", "details", "created_at"]


class DeviceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Your own devices; device administrators may pass scope=all to see the whole organization."""

    queryset = Device.objects.none()
    serializer_class = DeviceSerializer
    filterset_fields = ["trust_state", "user"]
    search_fields = ["name", "user__full_name", "user__email"]
    ordering_fields = ["last_seen_at", "created_at", "name"]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = Device.objects.filter(organization=user.organization).select_related("user", "trust_changed_by")
        if self.request.query_params.get("scope") == "all" and has_perm(user, Perm.DEVICES_MANAGE):
            return queryset
        if self.action in ("retrieve", "approve", "suspend", "revoke", "events") and has_perm(
            user, Perm.DEVICES_MANAGE
        ):
            return queryset
        return queryset.filter(user=user)

    @extend_schema(parameters=[OpenApiParameter("scope", str, enum=["all"])])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_update(self, serializer):
        if serializer.instance.user_id != self.request.user.pk:
            raise PermissionDenied("You can only rename your own devices.")
        serializer.save()

    def _change(self, request, operation):
        body = TrustChangeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        device = services.change_trust(
            actor=request.user, device=self.get_object(), operation=operation, reason=body.validated_data["reason"]
        )
        return Response(DeviceSerializer(device, context={"request": request}).data)

    @extend_schema(request=TrustChangeSerializer, responses={200: DeviceSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._change(request, "approve")

    @extend_schema(request=TrustChangeSerializer, responses={200: DeviceSerializer})
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._change(request, "suspend")

    @extend_schema(request=TrustChangeSerializer, responses={200: DeviceSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        return self._change(request, "revoke")

    @extend_schema(responses={200: DeviceEventSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        events = self.get_object().events.all()[:200]
        return Response(DeviceEventSerializer(events, many=True).data)


class RegisterDeviceView(APIView):
    """Identify this browser's device (issuing an HttpOnly device cookie the first time). Safe to call on every
    app start: it also refreshes last-seen and compares the fingerprint."""

    mfa_exempt = True

    @extend_schema(request=RegisterSerializer, responses={200: DeviceSerializer, 201: DeviceSerializer})
    def post(self, request):
        body = RegisterSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        device, raw_token = services.register_or_refresh(request, **body.validated_data)
        request._sv_device = device  # so is_current reflects the cookie we are about to set
        response = Response(
            DeviceSerializer(device, context={"request": request}).data,
            status=status.HTTP_201_CREATED if raw_token else status.HTTP_200_OK,
        )
        if raw_token:
            services.set_device_cookie(response, raw_token)
        return response


class CurrentDeviceView(APIView):
    mfa_exempt = True

    @extend_schema(responses={200: DeviceSerializer})
    def get(self, request):
        device = services.device_from_request(request)
        if device is None:
            return Response({"detail": "This browser has no registered device."}, status=status.HTTP_404_NOT_FOUND)
        return Response(DeviceSerializer(device, context={"request": request}).data)


# --------------------------------------------------------------------------- anomaly alerts


class AlertSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    device_name = serializers.CharField(source="device.name", read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source="reviewed_by.full_name", read_only=True, default=None)

    class Meta:
        model = AnomalyAlert
        fields = [
            "id",
            "type",
            "severity",
            "status",
            "summary",
            "details",
            "user",
            "user_name",
            "device",
            "device_name",
            "ip_address",
            "reviewed_by_name",
            "reviewed_at",
            "review_note",
            "created_at",
        ]
        read_only_fields = fields


class ReviewSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class AlertViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AnomalyAlert.objects.none()
    serializer_class = AlertSerializer
    permission_classes = [requires(Perm.ALERTS_MANAGE)]
    filterset_fields = ["status", "severity", "type", "user"]
    ordering_fields = ["created_at", "severity"]

    def get_queryset(self):
        return AnomalyAlert.objects.filter(organization=self.request.user.organization).select_related(
            "user", "device", "reviewed_by"
        )

    def _review(self, request, new_status):
        body = ReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        alert = self.get_object()
        previous = alert.status
        alert.status = new_status
        alert.reviewed_by = request.user
        alert.reviewed_at = timezone.now()
        alert.review_note = body.validated_data["note"].strip()
        alert.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
        audit.record(
            AuditAction.ANOMALY_REVIEW,
            actor=request.user,
            target=alert,
            target_type="anomaly_alert",
            reason=alert.review_note,
            metadata={"from": previous, "to": new_status, "type": alert.type},
        )
        return Response(AlertSerializer(alert).data)

    @extend_schema(request=ReviewSerializer, responses={200: AlertSerializer})
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return self._review(request, AnomalyAlert.Status.ACKNOWLEDGED)

    @extend_schema(request=ReviewSerializer, responses={200: AlertSerializer})
    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        return self._review(request, AnomalyAlert.Status.DISMISSED)
