from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditOutcome
from apps.devices.models import AnomalyAlert, Device
from apps.vault.models import Credential

from .vault_helpers import STRONG_SECRET, create_credential

pytestmark = pytest.mark.django_db

URL = "/api/v1/dashboard/"


def test_personal_dashboard_counts(client_for, employee, make_user):
    client = client_for(employee)
    colleague = make_user()
    a = create_credential(client, title="A").json()["id"]
    create_credential(client, title="B")  # same secret as A: reused
    weak = create_credential(client, title="Weak key", secret_type="API_KEY", password="abc").json()["id"]
    Credential.objects.filter(pk=weak).update(expires_at=timezone.localdate() - timedelta(days=1))
    Credential.objects.filter(pk=a).update(expires_at=timezone.localdate() + timedelta(days=3))
    theirs = create_credential(client_for(colleague), title="Theirs", password="Zk4#Shared-With-Me-881!").json()["id"]
    client_for(colleague).post(
        f"/api/v1/vault/credentials/{theirs}/share/", {"grantee": str(employee.id), "permission": "VIEW"}, format="json"
    )
    client.post(f"/api/v1/vault/credentials/{a}/reveal/", {}, format="json")
    Device.objects.create(
        organization=employee.organization, user=employee, name="Laptop", token_hash="d" * 64, trust_state="TRUSTED"
    )

    body = client.get(URL).json()
    me = body["me"]
    assert body["organization"] is None  # employees see only their own figures
    assert (me["credentials"], me["shared_with_me"], me["expiring_soon"], me["expired"], me["weak"], me["reused"]) == (
        3,
        1,
        1,
        1,
        1,
        2,
    )
    assert me["devices"] == {"trusted": 1, "not_trusted": 0}
    assert [s["label"] for s in me["strength"]] == ["very_weak", "weak", "fair", "strong", "very_strong"]
    assert sum(s["count"] for s in me["strength"]) == 3
    assert len(me["activity"]) == 7 and me["activity"][-1]["count"] == 1
    assert STRONG_SECRET not in str(body)


def test_organization_overview_for_security_staff(client_for, sec_admin, employee, other_admin):
    create_credential(client_for(employee))
    create_credential(client_for(other_admin), title="Other org")
    AnomalyAlert.objects.create(
        organization=employee.organization, user=employee, type="REVEAL_BURST", severity="HIGH", summary="x"
    )
    client_for(sec_admin).post(
        "/api/v1/lockdown/activate/",
        {
            "scope": "USER",
            "target_user": str(employee.id),
            "reason": "Investigating odd access",
            "password": "Sturdy-Test-Passphrase-42",
        },
        format="json",
    )
    org = client_for(sec_admin).get(URL).json()["organization"]
    assert org["credentials"] == 1  # the other organization's credential is not counted
    assert org["open_alerts"] == {"LOW": 0, "MEDIUM": 0, "HIGH": 1}
    assert len(org["active_lockdowns"]) == 1 and org["active_lockdowns"][0]["scope"] == "USER"
    assert org["recent_security_events"][0]["action"] == "LOCKDOWN"
    assert len(org["activity"]) == 7


def test_activity_covers_exactly_the_last_seven_days_of_successful_access(client_for, employee, sec_admin):
    now = timezone.now()

    def access(actor, days_ago, action=AuditAction.REVEAL, outcome=AuditOutcome.SUCCESS):
        with mock.patch("django.utils.timezone.now", return_value=now - timedelta(days=days_ago)):
            audit.record(action, actor=actor, target_type="credential", outcome=outcome)

    access(employee, 7)  # one day before the window: not counted
    access(employee, 6)  # first day of the window
    access(employee, 0, action=AuditAction.COPY)
    access(employee, 0, outcome=AuditOutcome.DENIED)  # refused attempts are not access
    access(sec_admin, 0)  # someone else's: only in the organization figures

    me = client_for(employee).get(URL).json()["me"]["activity"]
    org = client_for(sec_admin).get(URL).json()["organization"]["activity"]
    assert [d["count"] for d in me] == [1, 0, 0, 0, 0, 0, 1]
    assert [d["count"] for d in org] == [1, 0, 0, 0, 0, 0, 2]
    assert me[0]["date"] == (timezone.localdate(now) - timedelta(days=6)).isoformat()
    assert me[-1]["date"] == timezone.localdate(now).isoformat()
