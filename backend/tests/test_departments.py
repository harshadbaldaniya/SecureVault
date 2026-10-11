from apps.accounts.models import User
from apps.departments.models import Department

DEPTS = "/api/v1/departments/"


def test_admin_creates_department_with_normalised_code(client_for, admin):
    response = client_for(admin).post(DEPTS, {"name": "Engineering", "code": " eng "}, format="json")
    assert response.status_code == 201
    assert response.json()["code"] == "ENG"
    assert response.json()["employee_count"] == 0
    assert Department.objects.get(code="ENG").organization == admin.organization


def test_duplicate_code_rejected_within_org_but_allowed_across_orgs(client_for, admin, other_admin):
    client_for(admin).post(DEPTS, {"name": "Engineering", "code": "ENG"}, format="json")
    duplicate = client_for(admin).post(DEPTS, {"name": "Engineering 2", "code": "eng"}, format="json")
    assert duplicate.status_code == 400
    assert "code" in duplicate.json()["error"]["details"]
    assert client_for(other_admin).post(DEPTS, {"name": "Eng", "code": "ENG"}, format="json").status_code == 201


def test_employee_count_counts_only_active_members(client_for, admin, make_user, org):
    dept = Department.objects.create(organization=org, name="Ops", code="OPS")
    make_user(department=dept)
    make_user(department=dept)
    make_user(department=dept, status=User.Status.SUSPENDED)
    data = client_for(admin).get(f"{DEPTS}{dept.id}/").json()
    assert data["employee_count"] == 2


def test_department_with_members_cannot_be_deleted(client_for, admin, make_user, org):
    dept = Department.objects.create(organization=org, name="Ops", code="OPS")
    make_user(department=dept)
    response = client_for(admin).delete(f"{DEPTS}{dept.id}/")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert Department.objects.filter(pk=dept.pk).exists()


def test_empty_department_can_be_deleted(client_for, admin, org):
    dept = Department.objects.create(organization=org, name="Temp", code="TMP")
    assert client_for(admin).delete(f"{DEPTS}{dept.id}/").status_code == 204
