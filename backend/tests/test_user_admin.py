import pytest

from apps.accounts import services
from apps.accounts.models import User
from apps.departments.models import Department
from core.exceptions import ServiceError

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users/"


def test_admin_updates_role_and_department(client_for, admin, employee, org):
    dept = Department.objects.create(organization=org, name="Ops", code="OPS")
    response = client_for(admin).patch(
        f"{USERS}{employee.id}/", {"role": "SEC_ADMIN", "department": str(dept.id)}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["role"] == "SEC_ADMIN"
    assert response.json()["department_name"] == "Ops"


def test_email_is_read_only(client_for, admin, employee):
    client_for(admin).patch(f"{USERS}{employee.id}/", {"email": "evil@example.test"}, format="json")
    employee.refresh_from_db()
    assert employee.email != "evil@example.test"


def test_search_and_filter(client_for, admin, make_user):
    make_user(full_name="Zara Zebra", role=User.Role.SEC_ADMIN)
    client = client_for(admin)
    assert [u["full_name"] for u in client.get(USERS, {"search": "zebra"}).json()["results"]] == ["Zara Zebra"]
    roles = {u["role"] for u in client.get(USERS, {"role": "SEC_ADMIN"}).json()["results"]}
    assert roles == {"SEC_ADMIN"}


def test_admin_cannot_change_own_role_or_status(client_for, admin):
    client = client_for(admin)
    for change in ({"role": "EMPLOYEE"}, {"status": "SUSPENDED"}):
        response = client.patch(f"{USERS}{admin.id}/", change, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "self_change"


def test_last_active_org_admin_is_protected(admin, sec_admin):
    with pytest.raises(ServiceError) as exc:
        services.update_user(actor=sec_admin, user=admin, changes={"role": User.Role.EMPLOYEE})
    assert exc.value.error_code == "last_admin"


def test_admin_can_demote_another_admin_when_one_remains(client_for, admin, make_user):
    second = make_user(role=User.Role.ORG_ADMIN)
    response = client_for(admin).patch(f"{USERS}{second.id}/", {"role": "EMPLOYEE"}, format="json")
    assert response.status_code == 200


def test_suspending_user_kills_their_sessions_immediately(client_for, admin, employee):
    employee_client = client_for(employee)
    assert employee_client.get("/api/v1/auth/me/").status_code == 200
    response = client_for(admin).patch(f"{USERS}{employee.id}/", {"status": "SUSPENDED"}, format="json")
    assert response.status_code == 200
    assert employee.sessions.count() == 0
    assert employee_client.get("/api/v1/auth/me/").status_code == 401


def test_invited_user_cannot_be_activated_by_admin(client_for, admin, make_user):
    invited = make_user(status=User.Status.INVITED)
    response = client_for(admin).patch(f"{USERS}{invited.id}/", {"status": "ACTIVE"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_status"
