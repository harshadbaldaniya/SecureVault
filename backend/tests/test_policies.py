import pytest

from apps.audit.models import AuditAction, AuditLog
from apps.policies.models import SecurityPolicy

pytestmark = pytest.mark.django_db

POLICY = "/api/v1/policy/"


def test_members_can_read_default_policy(client_for, employee):
    data = client_for(employee).get(POLICY).json()
    assert data["min_password_length"] == 14
    assert data["require_device_trust"] is False
    assert SecurityPolicy.objects.filter(organization=employee.organization).count() == 1


def test_employee_cannot_change_policy(client_for, employee):
    response = client_for(employee).patch(POLICY, {"require_device_trust": True}, format="json")
    assert response.status_code == 403


@pytest.mark.parametrize("role_fixture", ["admin", "sec_admin"])
def test_admins_change_policy_and_change_is_audited_with_diff(client_for, request, role_fixture):
    user = request.getfixturevalue(role_fixture)
    response = client_for(user).patch(POLICY, {"require_device_trust": True, "min_password_length": 16}, format="json")
    assert response.status_code == 200
    entry = AuditLog.objects.get(action=AuditAction.POLICY_CHANGE)
    assert entry.actor_id == user.id
    assert entry.metadata["changes"] == {
        "min_password_length": {"from": 14, "to": 16},
        "require_device_trust": {"from": False, "to": True},
    }


def test_unchanged_values_produce_no_audit_entry(client_for, admin):
    client_for(admin).patch(POLICY, {"allow_view_once": True}, format="json")
    assert not AuditLog.objects.filter(action=AuditAction.POLICY_CHANGE).exists()


@pytest.mark.parametrize("payload", [{"min_password_length": 4}, {"max_share_duration_days": 0}])
def test_policy_values_are_range_checked(client_for, admin, payload):
    assert client_for(admin).patch(POLICY, payload, format="json").status_code == 400


def test_policies_are_per_organization(client_for, admin, other_admin):
    client_for(admin).patch(POLICY, {"require_mfa": True}, format="json")
    assert client_for(other_admin).get(POLICY).json()["require_mfa"] is False
