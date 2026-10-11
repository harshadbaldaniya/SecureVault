import pytest

from apps.services_catalog.models import ServiceCatalog

pytestmark = pytest.mark.django_db

SERVICES = "/api/v1/services/"


def test_admin_creates_service_and_members_can_read(client_for, admin, employee):
    payload = {"name": "AWS Console", "category": "CLOUD", "base_url": "https://console.aws.amazon.com"}
    assert client_for(admin).post(SERVICES, payload, format="json").status_code == 201
    names = [s["name"] for s in client_for(employee).get(SERVICES).json()["results"]]
    assert names == ["AWS Console"]


def test_employee_and_security_admin_cannot_change_catalog(client_for, employee, sec_admin):
    for user in (employee, sec_admin):
        assert client_for(user).post(SERVICES, {"name": "X"}, format="json").status_code == 403


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "ftp://files.example.test", "file:///etc/passwd", "data:text/html,hi"]
)
def test_only_http_and_https_urls_are_accepted(client_for, admin, url):
    response = client_for(admin).post(SERVICES, {"name": "Bad", "base_url": url, "icon_url": url}, format="json")
    assert response.status_code == 400
    assert {"base_url", "icon_url"} <= set(response.json()["error"]["details"])


@pytest.mark.parametrize("port", [0, 65536])
def test_port_must_be_valid(client_for, admin, port):
    assert client_for(admin).post(SERVICES, {"name": "DB", "default_port": port}, format="json").status_code == 400


def test_service_names_are_unique_per_org_case_insensitively(client_for, admin, other_admin):
    client_for(admin).post(SERVICES, {"name": "GitHub"}, format="json")
    duplicate = client_for(admin).post(SERVICES, {"name": "github "}, format="json")
    assert duplicate.status_code == 400
    assert client_for(other_admin).post(SERVICES, {"name": "GitHub"}, format="json").status_code == 201


def test_other_org_services_are_invisible(client_for, admin, other_org):
    foreign = ServiceCatalog.objects.create(organization=other_org, name="Secret Tool")
    client = client_for(admin)
    assert client.get(SERVICES).json()["count"] == 0
    assert client.get(f"{SERVICES}{foreign.id}/").status_code == 404
    assert client.delete(f"{SERVICES}{foreign.id}/").status_code == 404
