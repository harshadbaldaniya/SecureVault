"""Role checks and organization isolation, enforced server-side."""

import pytest

from apps.departments.models import Department

USERS = "/api/v1/users/"
DEPTS = "/api/v1/departments/"
INVITES = "/api/v1/invitations/"


@pytest.mark.parametrize(
    "method,url,payload",
    [
        ("get", USERS, None),
        ("post", DEPTS, {"name": "Ops", "code": "OPS"}),
        ("post", INVITES, {"email": "new@example.test", "full_name": "New"}),
        ("get", INVITES, None),
    ],
)
def test_employee_is_denied_admin_endpoints(client_for, employee, method, url, payload):
    response = getattr(client_for(employee), method)(url, payload, format="json")
    assert response.status_code == 403


def test_employee_can_read_departments(client_for, employee):
    assert client_for(employee).get(DEPTS).status_code == 200


def test_security_admin_can_view_but_not_manage_users(client_for, sec_admin, employee):
    client = client_for(sec_admin)
    assert client.get(USERS).status_code == 200
    assert client.patch(f"{USERS}{employee.id}/", {"role": "ORG_ADMIN"}, format="json").status_code == 403
    assert client.post(DEPTS, {"name": "Ops", "code": "OPS"}, format="json").status_code == 403
    assert client.post(INVITES, {"email": "x@example.test", "full_name": "X"}, format="json").status_code == 403


def test_employee_cannot_escalate_own_role(client_for, employee):
    response = client_for(employee).patch(f"{USERS}{employee.id}/", {"role": "ORG_ADMIN"}, format="json")
    assert response.status_code == 403
    employee.refresh_from_db()
    assert employee.role == "EMPLOYEE"


def test_lists_only_show_own_organization(client_for, admin, other_admin, other_org):
    Department.objects.create(organization=other_org, name="Secret Dept", code="SEC")
    client = client_for(admin)
    user_emails = {u["email"] for u in client.get(USERS).json()["results"]}
    assert other_admin.email not in user_emails
    assert client.get(DEPTS).json()["count"] == 0


def test_other_organization_records_return_404(client_for, admin, other_admin, other_org):
    dept = Department.objects.create(organization=other_org, name="Finance", code="FIN")
    client = client_for(admin)
    assert client.get(f"{DEPTS}{dept.id}/").status_code == 404
    assert client.patch(f"{DEPTS}{dept.id}/", {"name": "Hacked"}, format="json").status_code == 404
    assert client.delete(f"{DEPTS}{dept.id}/").status_code == 404
    assert client.get(f"{USERS}{other_admin.id}/").status_code == 404
    assert client.patch(f"{USERS}{other_admin.id}/", {"status": "SUSPENDED"}, format="json").status_code == 404
    dept.refresh_from_db()
    other_admin.refresh_from_db()
    assert dept.name == "Finance"
    assert other_admin.status == "ACTIVE"


def test_cannot_reference_other_organization_objects(client_for, admin, employee, other_admin, other_org):
    foreign_dept = Department.objects.create(organization=other_org, name="Finance", code="FIN")
    client = client_for(admin)

    response = client.post(DEPTS, {"name": "Ops", "code": "OPS", "head": str(other_admin.id)}, format="json")
    assert response.status_code == 400
    assert "head" in response.json()["error"]["details"]

    response = client.patch(f"{USERS}{employee.id}/", {"department": str(foreign_dept.id)}, format="json")
    assert response.status_code == 400

    response = client.post(
        INVITES, {"email": "n@example.test", "full_name": "N", "department": str(foreign_dept.id)}, format="json"
    )
    assert response.status_code == 400
