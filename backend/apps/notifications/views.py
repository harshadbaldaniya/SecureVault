from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "priority", "title", "message", "link", "is_read", "read_at", "created_at"]
        read_only_fields = fields


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Each user sees only their own notifications."""

    queryset = Notification.objects.none()  # for schema generation; get_queryset() scopes to the caller
    serializer_class = NotificationSerializer
    filterset_fields = ["is_read", "type", "priority"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @extend_schema(request=None, responses={200: NotificationSerializer})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return Response(NotificationSerializer(notification).data)

    @extend_schema(request=None, responses={200: inline_serializer("ReadAll", {"updated": serializers.IntegerField()})})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return Response({"updated": updated})

    @extend_schema(responses={200: inline_serializer("UnreadCount", {"unread": serializers.IntegerField()})})
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": self.get_queryset().filter(is_read=False).count()})
