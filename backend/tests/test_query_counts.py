"""Query optimization: a list endpoint must issue the same number of queries however many rows it returns.

Each case seeds a few rows, counts the queries a GET issues, adds more rows (still within one page) and counts again.
An N+1 pattern (a query per row for a related object or a computed field) shows up as a count that grows.
"""

import itertools
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.access_requests import services as access_requests
from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.departments.models import Department
from apps.devices.models import AnomalyAlert, Device
from apps.lockdown.models import LockdownState
from apps.notifications.services import notify
from apps.services_catalog.models import ServiceCatalog
from apps.sharing import services as sharing
from apps.vault.models import Credential

from .vault_helpers import create_credential

pytestmark = pytest.mark.django_db

SMALL, LARGE = 3, 12  # both fit in one page (25)
_serial = itertools.count()


def queries_for(client, url: str) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url)
    assert response.status_code == 200, (url, response.content[:300])
    return len(captured)


def grow(client, url, seed, *, small=SMALL, large=LARGE):
    """Seed `small` rows, measure, seed the rest, measure again; the two counts must match."""
    seed(small)
    assert client.get(url).json()["count"] >= small  # warm-up request: caches (content types, policies) fill once
    before = queries_for(client, url)
    seed(large - small)
    body = client.get(url).json()
    assert body["count"] >= large, "the seed did not create enough rows to prove anything"
    after = queries_for(client, url)
    return before, after


@pytest.fixture
def world(org, admin, employee, make_user):
    colleagues = [make_user(full_name=f"Colleague {i}") for i in range(LARGE + 2)]
    engineering = Department.objects.create(organization=org, name="Engineering", code="ENG")
    User.objects.filter(pk__in=[c.pk for c in colleagues]).update(department=engineering)
    service = ServiceCatalog.objects.create(organization=org, name="AWS", category="CLOUD", base_url="https://aws.test")
    return {"org": org, "admin": admin, "employee": employee, "colleagues": colleagues, "service": service}


def test_credentials_list(client_for, world):
    client = client_for(world["employee"])
    service = world["service"]

    def seed(n):
        for _ in range(n):
            create_credential(client, title=f"Cred {next(_serial)}", service=str(service.pk), tags=["a", "b"])

    before, after = grow(client, "/api/v1/vault/credentials/", seed)
    assert before == after


def test_credentials_list_with_shared_items(client_for, world):
    owner, reader = world["colleagues"][0], world["employee"]
    owner_client = client_for(owner)

    def seed(n):
        for _ in range(n):
            credential_id = create_credential(owner_client, title=f"Shared {next(_serial)}").json()["id"]
            credential = Credential.objects.get(pk=credential_id)
            sharing.create_share(actor=owner, credential=credential, grantee=reader, permission="EDIT")

    before, after = grow(client_for(reader), "/api/v1/vault/credentials/?scope=shared", seed)
    assert before == after


def test_shares_list_given_and_received(client_for, world):
    owner, reader = world["employee"], world["colleagues"][0]
    owner_client, reader_client = client_for(owner), client_for(reader)

    def seed(n):
        for _ in range(n):
            credential_id = create_credential(owner_client, title=f"S {next(_serial)}").json()["id"]
            sharing.create_share(
                actor=owner, credential=Credential.objects.get(pk=credential_id), grantee=reader, permission="VIEW"
            )

    given, received = "/api/v1/shares/?direction=given", "/api/v1/shares/?direction=received"
    seed(SMALL)
    for client, url in ((owner_client, given), (reader_client, received)):
        client.get(url)
    before = (queries_for(owner_client, given), queries_for(reader_client, received))
    seed(LARGE - SMALL)
    assert owner_client.get(given).json()["count"] == LARGE
    after = (queries_for(owner_client, given), queries_for(reader_client, received))
    assert before == after


def test_access_request_boxes(client_for, world):
    approver, requester = world["employee"], world["colleagues"][0]
    approver_client, requester_client = client_for(approver), client_for(requester)

    def seed(n):
        for _ in range(n):
            credential_id = create_credential(approver_client, title=f"R {next(_serial)}", requestable=True).json()[
                "id"
            ]
            access_requests.create_request(
                requester=requester,
                credential=Credential.objects.get(pk=credential_id),
                permission="VIEW",
                duration_hours=4,
                reason="Need it for the release",
            )

    to_approve, mine = "/api/v1/access-requests/?box=to_approve", "/api/v1/access-requests/?box=mine"
    seed(SMALL)
    for client, url in ((approver_client, to_approve), (requester_client, mine)):
        client.get(url)
    before = (queries_for(approver_client, to_approve), queries_for(requester_client, mine))
    seed(LARGE - SMALL)
    assert approver_client.get(to_approve).json()["count"] == LARGE
    after = (queries_for(approver_client, to_approve), queries_for(requester_client, mine))
    assert before == after


def test_notifications_list(client_for, world):
    recipient = world["employee"]

    def seed(n):
        for _ in range(n):
            notify([recipient], "SHARE_CREATED", f"Title {next(_serial)}", "Body", link="/vault")

    before, after = grow(client_for(recipient), "/api/v1/notifications/", seed)
    assert before == after


def test_devices_lists(client_for, world):
    employee, admin = world["employee"], world["admin"]

    def seed(n):
        for _ in range(n):
            Device.objects.create(
                organization=world["org"],
                user=world["colleagues"][next(_serial) % len(world["colleagues"])],
                name=f"Device {next(_serial)}",
                token_hash=f"{next(_serial):064d}",
                trust_state="PENDING",
            )

    before, after = grow(client_for(admin), "/api/v1/devices/?scope=all", seed)
    assert before == after
    assert employee


def test_alerts_list(client_for, world):
    def seed(n):
        for _ in range(n):
            AnomalyAlert.objects.create(
                organization=world["org"],
                user=world["colleagues"][next(_serial) % len(world["colleagues"])],
                type="NEW_DEVICE",
                severity="LOW",
                summary="New device",
                device=Device.objects.create(
                    organization=world["org"],
                    user=world["employee"],
                    name=f"D{next(_serial)}",
                    token_hash=f"{next(_serial):064d}",
                ),
            )

    before, after = grow(client_for(world["admin"]), "/api/v1/alerts/", seed)
    assert before == after


def test_audit_log_list(client_for, world):
    def seed(n):
        for _ in range(n):
            audit.record(
                AuditAction.REVEAL,
                actor=world["colleagues"][next(_serial) % len(world["colleagues"])],
                target_type="credential",
                target_label=f"c{next(_serial)}",
            )

    before, after = grow(client_for(world["admin"]), "/api/v1/audit-logs/", seed)
    assert before == after


def test_employee_and_department_lists(client_for, world, make_user):
    client = client_for(world["admin"])
    engineering = Department.objects.get(code="ENG")

    def seed_users(n):
        for _ in range(n):
            make_user(full_name=f"New hire {next(_serial)}", department=engineering)

    before, after = grow(client, "/api/v1/users/", seed_users)
    assert before == after

    def seed_departments(n):
        for _ in range(n):
            Department.objects.create(organization=world["org"], name=f"Dept {next(_serial)}", code=f"D{next(_serial)}")

    before, after = grow(client, "/api/v1/departments/", seed_departments)
    assert before == after


@pytest.mark.parametrize("report", ["audit", "credentials", "devices", "shares", "alerts", "lockdowns"])
def test_report_queries_do_not_grow_with_rows(client_for, world, report):
    admin = world["admin"]
    employee = world["employee"]
    employee_client = client_for(employee)

    def seed(n):
        for _ in range(n):
            credential_id = create_credential(employee_client, title=f"Rep {next(_serial)}").json()["id"]
            colleague = world["colleagues"][next(_serial) % len(world["colleagues"])]
            sharing.create_share(
                actor=employee,
                credential=Credential.objects.get(pk=credential_id),
                grantee=colleague,
                permission="VIEW",
                expires_at=timezone.now() + timedelta(days=2),
            )
            Device.objects.create(
                organization=world["org"],
                user=colleague,
                name=f"Dev {next(_serial)}",
                token_hash=f"{next(_serial):064d}",
            )
            AnomalyAlert.objects.create(
                organization=world["org"], user=colleague, type="NEW_NETWORK", severity="MEDIUM", summary="New network"
            )
            audit.record(AuditAction.REVEAL, actor=colleague, target_type="credential", target_label="x")
            LockdownState.objects.create(
                organization=world["org"],
                scope="USER",
                target_user=colleague,
                reason="Resolved drill",
                initiated_by=admin,
                is_active=False,
                resolved_at=timezone.now(),
                resolved_by=admin,
            )

    seed(SMALL)
    admin_client = client_for(admin)
    url = f"/api/v1/reports/{report}/"
    admin_client.get(url)  # warm-up
    before = queries_for(admin_client, url)
    seed(LARGE - SMALL)
    after = queries_for(admin_client, url)
    assert before == after


def test_dashboard_queries_do_not_grow_with_rows(client_for, world):
    employee = world["employee"]
    client = client_for(employee)

    def seed(n):
        for _ in range(n):
            create_credential(client, title=f"Dash {next(_serial)}")
            notify([employee], "SHARE_CREATED", f"T{next(_serial)}", "")

    seed(SMALL)
    admin_client = client_for(world["admin"])
    admin_client.get("/api/v1/dashboard/")
    client.get("/api/v1/dashboard/")
    mine_before, org_before = queries_for(client, "/api/v1/dashboard/"), queries_for(admin_client, "/api/v1/dashboard/")
    seed(LARGE - SMALL)
    assert queries_for(client, "/api/v1/dashboard/") == mine_before
    assert queries_for(admin_client, "/api/v1/dashboard/") == org_before
