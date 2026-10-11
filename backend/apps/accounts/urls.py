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
    *router.urls,
]
