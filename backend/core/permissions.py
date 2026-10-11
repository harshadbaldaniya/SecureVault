"""Role-based permission matrix and DRF permission classes.

This is the single place that maps roles to administrative permissions.
Resource-level checks (credential shares, device trust, lockdown) are added
by later phases on top of these; a role alone never grants access to a secret.
"""

from django.conf import settings
from rest_framework import exceptions
from rest_framework.permissions import SAFE_METHODS, BasePermission


class Perm:
    USERS_VIEW = "users.view"
    USERS_MANAGE = "users.manage"
    INVITATIONS_MANAGE = "invitations.manage"
    DEPARTMENTS_MANAGE = "departments.manage"
    SERVICES_MANAGE = "services.manage"
    POLICIES_MANAGE = "policies.manage"
    AUDIT_VIEW = "audit.view"
    # Incident response: revoke any grant / inspect delegation trees. Never grants access to a secret.
    SHARES_REVOKE_ANY = "shares.revoke_any"
    SHARES_VIEW_ALL = "shares.view_all"
    DEVICES_MANAGE = "devices.manage"
    ALERTS_MANAGE = "alerts.manage"
    LOCKDOWN_MANAGE = "lockdown.manage"
    REPORTS_VIEW = "reports.view"


_SECURITY_OPERATIONS = frozenset(
    {
        Perm.AUDIT_VIEW,
        Perm.SHARES_REVOKE_ANY,
        Perm.SHARES_VIEW_ALL,
        Perm.DEVICES_MANAGE,
        Perm.ALERTS_MANAGE,
        Perm.LOCKDOWN_MANAGE,
        Perm.REPORTS_VIEW,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "ORG_ADMIN": frozenset(
        {
            Perm.USERS_VIEW,
            Perm.USERS_MANAGE,
            Perm.INVITATIONS_MANAGE,
            Perm.DEPARTMENTS_MANAGE,
            Perm.SERVICES_MANAGE,
            Perm.POLICIES_MANAGE,
        }
    )
    | _SECURITY_OPERATIONS,
    "SEC_ADMIN": frozenset({Perm.USERS_VIEW, Perm.POLICIES_MANAGE}) | _SECURITY_OPERATIONS,
    "EMPLOYEE": frozenset(),
}


def permissions_for(user) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(getattr(user, "role", None), frozenset())


def has_perm(user, *perms: str) -> bool:
    granted = permissions_for(user)
    return all(perm in granted for perm in perms)


class IsActiveMember(BasePermission):
    """Default for every endpoint: authenticated, ACTIVE user in an ACTIVE organization.

    When the organization's policy requires MFA, users who have not enrolled are refused
    everywhere except views marked `mfa_exempt = True` (profile, logout, MFA setup).
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active and user.organization.status == "ACTIVE"):
            return False
        if not getattr(view, "lockdown_exempt", False):
            from apps.lockdown.services import LockdownActive, session_block  # local import: avoids app-loading cycle

            # Sessions are terminated when a lockdown starts; this also refuses any session that slipped through.
            if session_block(user) is not None:
                raise LockdownActive("Your access is suspended by an emergency lockdown.")
        if not getattr(view, "mfa_exempt", False):
            from apps.accounts.mfa import enrollment_required  # local import: avoids app-loading cycle

            if enrollment_required(user):
                raise exceptions.PermissionDenied(
                    "Your organization requires multi-factor authentication. Set it up to continue.",
                    code="mfa_enrollment_required",
                )
        return True


class ApiDocsEnabled(BasePermission):
    """Hides the OpenAPI schema and Swagger UI (404, as if the routes did not exist) unless SV_ENABLE_API_DOCS is on.

    Off by default outside DEBUG: the API surface is documented in docs/openapi.yaml, and the Swagger UI loads its
    assets from a CDN, which the production Content-Security-Policy does not allow.
    """

    def has_permission(self, request, view) -> bool:
        if not settings.ENABLE_API_DOCS:
            raise exceptions.NotFound()
        return True


def requires(*perms: str, read_open: bool = False) -> type[BasePermission]:
    """Build a permission class requiring `perms`.

    With read_open=True any active member may use safe (read-only) methods.
    """

    class RequiresPermission(BasePermission):
        def has_permission(self, request, view) -> bool:
            if not IsActiveMember().has_permission(request, view):
                return False
            if read_open and request.method in SAFE_METHODS:
                return True
            return has_perm(request.user, *perms)

    RequiresPermission.__name__ = "Requires_" + "_".join(p.replace(".", "_") for p in perms)
    return RequiresPermission
