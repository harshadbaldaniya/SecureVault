from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.register("users", views.UserViewSet, basename="user")
router.register("invitations", views.InvitationViewSet, basename="invitation")

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("auth/invitations/accept/", views.AcceptInvitationView.as_view(), name="auth-accept-invitation"),
    path("auth/mfa/verify/", views.MfaVerifyView.as_view(), name="auth-mfa-verify"),
    path("auth/mfa/totp/setup/", views.TotpSetupView.as_view(), name="auth-totp-setup"),
    path("auth/mfa/totp/confirm/", views.TotpConfirmView.as_view(), name="auth-totp-confirm"),
    path("auth/mfa/totp/disable/", views.TotpDisableView.as_view(), name="auth-totp-disable"),
    path("auth/mfa/recovery-codes/", views.RecoveryCodesView.as_view(), name="auth-recovery-codes"),
    path("auth/password/change/", views.PasswordChangeView.as_view(), name="auth-password-change"),
    path("auth/password-reset/", views.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("auth/password-reset/confirm/", views.PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    *router.urls,
]
