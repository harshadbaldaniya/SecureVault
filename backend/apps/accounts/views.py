import time

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditOutcome
from apps.devices import anomaly
from apps.lockdown import services as lockdown_services
from core import request_context
from core.exceptions import ServiceError
from core.http import no_store
from core.permissions import Perm, requires
from core.tenancy import OrgScopedQuerysetMixin
from core.throttling import StrictScopedRateThrottle

from . import mfa, services
from .models import Invitation, User
from .serializers import (
    AcceptInvitationSerializer,
    DetailSerializer,
    InvitationCreateSerializer,
    InvitationLinkSerializer,
    InvitationSerializer,
    LoginResultSerializer,
    LoginSerializer,
    MeSerializer,
    MfaCodeSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ReauthSerializer,
    RecoveryCodesSerializer,
    ResetLinkSerializer,
    TotpSetupSerializer,
    UserAdminSerializer,
)

MFA_PENDING_KEY = "mfa_pending"
MFA_PENDING_SECONDS = 300
MFA_MAX_ATTEMPTS = 5
LOCKED_MESSAGE = "Too many failed sign-in attempts. Try again later."


def audit_login_failure(email: str, reason: str) -> None:
    # Attributed to the account's organization when the email exists, otherwise to the global chain.
    # The attempted email is recorded as the target; passwords and codes never are.
    known = User.objects.filter(email__iexact=email).select_related("organization").first()
    audit.record(
        AuditAction.LOGIN,
        outcome=AuditOutcome.FAILURE,
        organization=known.organization if known else None,
        target_type="user",
        target_id=str(known.pk) if known else "",
        target_label=email.lower(),
        reason=reason,
        fail_silently=True,
    )


def refuse_if_locked_down(user: User) -> None:
    """Called only after the password checked out, so it reveals nothing to someone guessing emails."""
    if lockdown_services.session_block(user) is not None:
        audit_login_failure(user.email, "lockdown_active")
        raise lockdown_services.LockdownActive(
            "SecureVault is in emergency lockdown. You cannot sign in until the security team lifts it."
        )


def complete_login(request, user: User, method: str | None) -> Response:
    refuse_if_locked_down(user)  # re-checked here: a lockdown may have started during the MFA step
    services.clear_login_failures(user.email)
    ctx = request_context.current()
    anomaly.evaluate_login(user, ctx.ip_address if ctx else None)  # before this sign-in joins the history
    with transaction.atomic():
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # rotates session + CSRF
        audit.record(
            AuditAction.LOGIN,
            actor=user,
            target=user,
            target_type="user",
            metadata={"second_factor": method} if method else None,
        )
    return Response({"mfa_required": False, "user": MeSerializer(user).data})


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
    """Step 1: password. If the user has MFA, only a short-lived pending state is created."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [StrictScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, responses={200: LoginResultSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        if services.is_login_locked(email):
            audit_login_failure(email, "locked")
            raise ServiceError(LOCKED_MESSAGE, "login_locked", status_code=429)

        user = authenticate(request, username=email, password=password)
        if user is None or user.organization.status != "ACTIVE":
            services.record_login_failure(email)
            audit_login_failure(email, "invalid_credentials")
            # One message for unknown email, wrong password and inactive account (no enumeration).
            raise ServiceError("Invalid email or password.", "invalid_credentials")

        refuse_if_locked_down(user)
        if mfa.has_confirmed_totp(user):
            request.session.cycle_key()  # fresh anonymous session to hold the pending state
            request.session[MFA_PENDING_KEY] = {
                "user_id": str(user.pk),
                "expires": time.time() + MFA_PENDING_SECONDS,
                "attempts": 0,
            }
            return Response({"mfa_required": True, "user": None})
        return complete_login(request, user, None)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class MfaVerifyView(APIView):
    """Step 2: TOTP or recovery code for the pending sign-in."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [StrictScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=MfaCodeSerializer, responses={200: LoginResultSerializer})
    def post(self, request):
        serializer = MfaCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pending = request.session.get(MFA_PENDING_KEY)
        user = None
        if pending and pending["expires"] > time.time():
            user = User.objects.select_related("organization").filter(pk=pending["user_id"]).first()
        if user is None or not user.is_active or user.organization.status != "ACTIVE":
            request.session.pop(MFA_PENDING_KEY, None)
            raise ServiceError("Your sign-in attempt expired. Sign in again.", "mfa_session_expired")

        if services.is_login_locked(user.email):
            request.session.pop(MFA_PENDING_KEY, None)
            audit_login_failure(user.email, "locked")
            raise ServiceError(LOCKED_MESSAGE, "login_locked", status_code=429)

        method = mfa.verify_second_factor(user, serializer.validated_data["code"])
        if method is None:
            pending["attempts"] += 1
            if pending["attempts"] >= MFA_MAX_ATTEMPTS:
                request.session.pop(MFA_PENDING_KEY, None)
            else:
                request.session[MFA_PENDING_KEY] = pending
            services.record_login_failure(user.email)
            audit_login_failure(user.email, "invalid_mfa_code")
            raise ServiceError("Invalid verification code.", "invalid_mfa_code")

        request.session.pop(MFA_PENDING_KEY, None)
        return complete_login(request, user, method)


class LogoutView(APIView):
    mfa_exempt = True
    lockdown_exempt = True  # signing out must always work

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        with transaction.atomic():
            audit.record(AuditAction.LOGOUT, target=request.user, target_type="user")
            logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    mfa_exempt = True
    lockdown_exempt = True  # lets a reconnecting client learn that a lockdown is active

    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        return Response(MeSerializer(request.user).data)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(sensitive_post_parameters("password", "token"), name="dispatch")
class AcceptInvitationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [StrictScopedRateThrottle]
    throttle_scope = "invitation_accept"

    @extend_schema(request=AcceptInvitationSerializer, responses={200: DetailSerializer})
    def post(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.accept_invitation(
            raw_token=serializer.validated_data["token"], password=serializer.validated_data["password"]
        )
        return Response({"detail": "Account activated. You can now sign in."})


# --------------------------------------------------------------------------- MFA management


class TotpSetupView(APIView):
    mfa_exempt = True  # must stay reachable when the policy forces enrolment

    @extend_schema(request=None, responses={200: TotpSetupSerializer})
    def post(self, request):
        secret, uri = mfa.begin_totp_setup(request.user)
        return no_store(Response({"secret": secret, "otpauth_uri": uri}))


@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class TotpConfirmView(APIView):
    mfa_exempt = True

    @extend_schema(request=MfaCodeSerializer, responses={200: RecoveryCodesSerializer})
    def post(self, request):
        serializer = MfaCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = mfa.confirm_totp(request.user, serializer.validated_data["code"])
        # Sessions opened before MFA existed never passed a second factor: end them.
        services.revoke_sessions([request.user], keep_session_key=request.session.session_key)
        return no_store(Response({"recovery_codes": codes}))


@method_decorator(sensitive_post_parameters("password", "code"), name="dispatch")
class TotpDisableView(APIView):
    @extend_schema(request=ReauthSerializer, responses={204: None})
    def post(self, request):
        serializer = ReauthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mfa.disable_totp(request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(sensitive_post_parameters("password", "code"), name="dispatch")
class RecoveryCodesView(APIView):
    @extend_schema(request=ReauthSerializer, responses={200: RecoveryCodesSerializer})
    def post(self, request):
        serializer = ReauthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = mfa.regenerate_recovery_codes(request.user, **serializer.validated_data)
        return no_store(Response({"recovery_codes": codes}))


# --------------------------------------------------------------------------- passwords


@method_decorator(sensitive_post_parameters("current_password", "new_password"), name="dispatch")
class PasswordChangeView(APIView):
    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_password(request, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [StrictScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetRequestSerializer, responses={202: DetailSerializer})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"])
        # Identical answer whether or not the account exists.
        return Response(
            {"detail": "If an account exists for that email, a reset link has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(sensitive_post_parameters("password", "token"), name="dispatch")
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [StrictScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: DetailSerializer})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_password_reset(
            raw_token=serializer.validated_data["token"], password=serializer.validated_data["password"]
        )
        return Response({"detail": "Password updated. Sign in with your new password."})


# --------------------------------------------------------------------------- administration


class UserViewSet(
    OrgScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Employee directory for admins. Users are created only through invitations."""

    queryset = User.objects.select_related("department")
    serializer_class = UserAdminSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]
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

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"], url_path="reset-mfa")
    def reset_mfa(self, request, pk=None):
        mfa.admin_reset_mfa(actor=request.user, user=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={201: ResetLinkSerializer})
    @action(detail=True, methods=["post"], url_path="password-reset-link")
    def password_reset_link(self, request, pk=None):
        url = services.issue_admin_reset_link(actor=request.user, user=self.get_object())
        return no_store(Response({"reset_url": url}, status=status.HTTP_201_CREATED))


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
        return no_store(Response(data, status=http_status))
