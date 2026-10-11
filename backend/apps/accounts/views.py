from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.exceptions import ServiceError
from core.permissions import Perm, requires
from core.tenancy import OrgScopedQuerysetMixin

from . import services
from .models import Invitation, User
from .serializers import (
    AcceptInvitationSerializer,
    DetailSerializer,
    InvitationCreateSerializer,
    InvitationLinkSerializer,
    InvitationSerializer,
    LoginSerializer,
    MeSerializer,
    UserAdminSerializer,
)

# --------------------------------------------------------------------------- authentication


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the CSRF cookie so the SPA can send X-CSRFToken on its first POST."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={204: None})
    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")  # login CSRF: DRF skips CSRF for anonymous requests
@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, responses={200: MeSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        if services.is_login_locked(email):
            raise ServiceError(
                "Too many failed sign-in attempts. Try again later.", "login_locked", status_code=429
            )

        user = authenticate(request, username=email, password=password)
        if user is None or user.organization.status != "ACTIVE":
            services.record_login_failure(email)
            # One message for unknown email, wrong password and inactive account (no enumeration).
            raise ServiceError("Invalid email or password.", "invalid_credentials")

        services.clear_login_failures(email)
        login(request, user)  # rotates the session key and CSRF token
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        return Response(MeSerializer(request.user).data)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(sensitive_post_parameters("password", "token"), name="dispatch")
class AcceptInvitationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "invitation_accept"

    @extend_schema(request=AcceptInvitationSerializer, responses={200: DetailSerializer})
    def post(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.accept_invitation(
            raw_token=serializer.validated_data["token"], password=serializer.validated_data["password"]
        )
        return Response({"detail": "Account activated. You can now sign in."})


# --------------------------------------------------------------------------- administration


class UserViewSet(
    OrgScopedQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Employee directory for admins. Users are created only through invitations."""

    queryset = User.objects.select_related("department")
    serializer_class = UserAdminSerializer
    http_method_names = ["get", "patch", "head", "options"]
    filterset_fields = ["role", "status", "department"]
    search_fields = ["full_name", "email"]
    ordering_fields = ["full_name", "email", "created_at", "last_login"]

    def get_permissions(self):
        perm = Perm.USERS_VIEW if self.request.method in ("GET", "HEAD", "OPTIONS") else Perm.USERS_MANAGE
        return [requires(perm)()]

    def perform_update(self, serializer):
        serializer.instance = services.update_user(
            actor=self.request.user, user=serializer.instance, changes=serializer.validated_data
        )


class InvitationViewSet(
    OrgScopedQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = Invitation.objects.select_related("user", "invited_by")
    serializer_class = InvitationSerializer
    permission_classes = [requires(Perm.INVITATIONS_MANAGE)]
    ordering_fields = ["created_at", "expires_at"]

    @extend_schema(request=InvitationCreateSerializer, responses={201: InvitationLinkSerializer})
    def create(self, request):
        serializer = InvitationCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        invitation, raw_token = services.invite_user(inviter=request.user, **serializer.validated_data)
        return self._with_link(invitation, raw_token, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={201: InvitationLinkSerializer})
    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        invitation, raw_token = services.resend_invitation(inviter=request.user, invitation=self.get_object())
        return self._with_link(invitation, raw_token, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: InvitationSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        invitation = services.revoke_invitation(self.get_object())
        return Response(InvitationSerializer(invitation).data)

    @staticmethod
    def _with_link(invitation, raw_token, http_status):
        # The link is returned exactly once, to the inviting admin, for out-of-band delivery.
        # It is never stored or logged. (Email delivery is a later enhancement.)
        data = InvitationSerializer(invitation).data
        data["invite_url"] = services.invitation_url(raw_token)
        return Response(data, status=http_status)
