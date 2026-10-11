"""Role-based permission matrix and DRF permission classes.

This is the single place that maps roles to administrative permissions.
Resource-level checks (credential shares, device trust, lockdown) are added
by later phases on top of these; a role alone never grants access to a secret.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class Perm:
    USERS_VIEW = "users.view"
    USERS_MANAGE = "users.manage"
    INVITATIONS_MANAGE = "invitations.manage"
    DEPARTMENTS_MANAGE = "departments.manage"
    SERVICES_MANAGE = "services.manage"
    POLICIES_MANAGE = "policies.manage"
    AUDIT_VIEW = "audit.view"


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "ORG_ADMIN": frozenset(
        {
            Perm.USERS_VIEW, Perm.USERS_MANAGE, Perm.INVITATIONS_MANAGE, Perm.DEPARTMENTS_MANAGE,
            Perm.SERVICES_MANAGE, Perm.POLICIES_MANAGE, Perm.AUDIT_VIEW,
        }
    ),
    "SEC_ADMIN": frozenset({Perm.USERS_VIEW, Perm.POLICIES_MANAGE, Perm.AUDIT_VIEW}),
    "EMPLOYEE": frozenset(),
}


def permissions_for(user) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(getattr(user, "role", None), frozenset())


def has_perm(user, *perms: str) -> bool:
    granted = permissions_for(user)
    return all(perm in granted for perm in perms)


class IsActiveMember(BasePermission):
    """Default for every endpoint: authenticated, ACTIVE user in an ACTIVE organization."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.organization.status == "ACTIVE"
        )


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
