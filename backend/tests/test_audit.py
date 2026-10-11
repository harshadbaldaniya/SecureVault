import json
from pathlib import Path
from unittest import mock

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.departments.models import Department

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

AUDIT = "/api/v1/audit-logs/"


def all_audit_text() -> str:
    return " ".join(str(row) for row in AuditLog.objects.values_list())


# --------------------------------------------------------------------------- what gets recorded


def test_successful_login_is_audited_with_request_context(anon, employee):
    response = anon.post("/api/v1/auth/login/", {"email": employee.email, "password": PASSWORD}, format="json")
    entry = AuditLog.objects.get(action=AuditAction.LOGIN, outcome=AuditOutcome.SUCCESS)
    assert entry.actor_id == employee.id
    assert entry.organization_id == employee.organization_id
    assert entry.ip_address == "127.0.0.1"
    assert entry.request_id == response["X-Request-ID"]


def test_failed_login_is_audited_without_the_password(anon, employee):
    anon.post("/api/v1/auth/login/", {"email": employee.email, "password": "Wrong-But-Secret-991"}, format="json")
    entry = AuditLog.objects.get(action=AuditAction.LOGIN, outcome=AuditOutcome.FAILURE)
    assert entry.organization_id == employee.organization_id
    assert entry.reason == "invalid_credentials"
    assert "Wrong-But-Secret-991" not in all_audit_text()


def test_failed_login_for_unknown_email_goes_to_global_chain(anon):
    anon.post("/api/v1/auth/login/", {"email": "ghost@example.test", "password": "whatever-123"}, format="json")
    entry = AuditLog.objects.get(action=AuditAction.LOGIN)
    assert entry.chain_key == "global"
    assert entry.organization_id is None


def test_logout_is_audited(client_for, employee):
    client_for(employee).post("/api/v1/auth/logout/")
    assert AuditLog.objects.filter(action=AuditAction.LOGOUT, actor_id=employee.id).exists()


def test_admin_actions_are_audited(client_for, admin, employee):
    client = client_for(admin)
    client.post("/api/v1/departments/", {"name": "Ops", "code": "OPS"}, format="json")
    client.patch(f"/api/v1/users/{employee.id}/", {"role": "SEC_ADMIN"}, format="json")
    response = client.post("/api/v1/invitations/", {"email": "n@example.test", "full_name": "N"}, format="json")
    token = response.json()["invite_url"].split("#token=")[1]

    assert AuditLog.objects.filter(action=AuditAction.CREATE, target_type="department").exists()
    edit = AuditLog.objects.get(action=AuditAction.EDIT, target_type="user")
    assert edit.metadata["role"] == {"from": "EMPLOYEE", "to": "SEC_ADMIN"}
    assert AuditLog.objects.filter(action=AuditAction.INVITE).exists()
    assert token not in all_audit_text()


def test_metadata_with_secret_like_keys_is_redacted(admin):
    entry = audit.record(
        AuditAction.EDIT,
        actor=admin,
        metadata={"password": "p@ss", "nested": {"api_key": "k-123", "items": [{"token": "t-9"}]}, "note": "ok"},
    )
    assert entry.metadata == {
        "password": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "items": [{"token": "[REDACTED]"}]},
        "note": "ok",
    }
    assert "p@ss" not in all_audit_text() and "k-123" not in all_audit_text()


def test_settings_about_secrets_are_not_redacted(admin):
    entry = audit.record(
        AuditAction.POLICY_CHANGE,
        actor=admin,
        metadata={"min_password_length": 16, "max_password_age_days": 90, "password_hint": "my dog"},
    )
    assert entry.metadata == {"min_password_length": 16, "max_password_age_days": 90, "password_hint": "[REDACTED]"}


def test_the_secret_type_label_is_kept_but_secret_values_are_not(admin):
    entry = audit.record(
        AuditAction.CREATE, actor=admin, metadata={"secret_type": "API_KEY", "secret": "hunter2", "secret_value": "x"}
    )
    assert entry.metadata == {"secret_type": "API_KEY", "secret": "[REDACTED]", "secret_value": "[REDACTED]"}


# --------------------------------------------------------------------------- integrity


def test_hash_chain_links_records_and_verifies(admin):
    entries = [audit.record(AuditAction.EDIT, actor=admin, metadata={"n": i}) for i in range(3)]
    assert [e.sequence for e in entries] == [1, 2, 3]
    assert entries[0].prev_hash == "0" * 64
    assert entries[1].prev_hash == entries[0].hash
    assert entries[2].prev_hash == entries[1].hash
    assert audit.verify_chain(audit.chain_key_for(admin.organization))["valid"] is True


def tamper(sql: str) -> None:
    """Simulates an attacker with table-owner rights who disables the trigger and edits rows."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush Django's deferred FK checks first
        cursor.execute("ALTER TABLE audit_auditlog DISABLE TRIGGER audit_auditlog_append_only")
        cursor.execute(sql)
        cursor.execute("ALTER TABLE audit_auditlog ENABLE TRIGGER audit_auditlog_append_only")


def test_tampering_is_detected(admin):
    for i in range(3):
        audit.record(AuditAction.EDIT, actor=admin, metadata={"n": i})
    tamper("UPDATE audit_auditlog SET reason = 'edited' WHERE sequence = 2")
    result = audit.verify_chain(audit.chain_key_for(admin.organization))
    assert result["valid"] is False
    assert result["broken_at_sequence"] == 2


def test_deleting_the_newest_record_is_detected(admin):
    for i in range(3):
        audit.record(AuditAction.EDIT, actor=admin, metadata={"n": i})
    tamper("DELETE FROM audit_auditlog WHERE sequence = 3")
    assert audit.verify_chain(audit.chain_key_for(admin.organization))["broken_at_sequence"] == 3


def test_orm_cannot_modify_or_delete_audit_records(admin):
    entry = audit.record(AuditAction.EDIT, actor=admin)
    entry.reason = "changed"
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()
    with pytest.raises(PermissionError):
        AuditLog.objects.filter(pk=entry.pk).update(reason="x")
    with pytest.raises(PermissionError):
        AuditLog.objects.all().delete()


@pytest.mark.parametrize("sql", ["UPDATE audit_auditlog SET reason = 'x'", "DELETE FROM audit_auditlog"])
def test_database_trigger_blocks_raw_sql_mutation(admin, sql):
    audit.record(AuditAction.EDIT, actor=admin)
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql)
    assert AuditLog.objects.count() == 1


def test_action_fails_closed_when_audit_write_fails(client_for, admin):
    with mock.patch("apps.audit.services._append", side_effect=RuntimeError("audit store down")):
        response = client_for(admin).post("/api/v1/departments/", {"name": "Ops", "code": "OPS"}, format="json")
    assert response.status_code == 500
    assert "audit store down" not in response.content.decode()
    assert not Department.objects.filter(code="OPS").exists()


def test_failed_login_still_denied_when_audit_write_fails(anon, employee):
    with mock.patch("apps.audit.services._append", side_effect=RuntimeError("audit store down")):
        response = anon.post("/api/v1/auth/login/", {"email": employee.email, "password": "nope-nope-1"}, format="json")
    assert response.status_code == 400


# --------------------------------------------------------------------------- API access


def test_employee_cannot_read_audit_logs(client_for, employee):
    assert client_for(employee).get(AUDIT).status_code == 403


def test_security_admin_reads_only_own_org_logs(client_for, sec_admin, other_admin):
    audit.record(AuditAction.EDIT, actor=other_admin, reason="other org event")
    audit.record(AuditAction.EDIT, actor=sec_admin, reason="own org event")
    response = client_for(sec_admin).get(AUDIT)
    assert response.status_code == 200
    reasons = {row["reason"] for row in response.json()["results"]}
    assert "own org event" in reasons
    assert "other org event" not in reasons


def test_audit_api_is_read_only(client_for, sec_admin):
    entry = audit.record(AuditAction.EDIT, actor=sec_admin)
    client = client_for(sec_admin)
    assert client.post(AUDIT, {"action": "LOGIN"}, format="json").status_code == 405
    assert client.patch(f"{AUDIT}{entry.pk}/", {"reason": "x"}, format="json").status_code == 405
    assert client.delete(f"{AUDIT}{entry.pk}/").status_code == 405


def test_audit_filters_and_verify_endpoint(client_for, sec_admin):
    audit.record(AuditAction.EDIT, actor=sec_admin)
    audit.record(AuditAction.POLICY_CHANGE, actor=sec_admin)
    client = client_for(sec_admin)
    actions = {row["action"] for row in client.get(AUDIT, {"action": "POLICY_CHANGE"}).json()["results"]}
    assert actions == {"POLICY_CHANGE"}
    verify = client.get(f"{AUDIT}verify/").json()
    assert verify["valid"] is True
    assert verify["checked"] >= 2


def test_shared_action_list_matches_the_backend():
    """The UI's action filters come from shared/audit-actions.json; a new action must be added there too."""
    shared = Path(__file__).resolve().parents[2] / "shared" / "audit-actions.json"
    assert json.loads(shared.read_text(encoding="utf-8")) == list(AuditAction.values)


def test_verify_audit_chain_command_reports_ok_and_fails_loudly_on_tampering(admin):
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    for i in range(3):
        audit.record(AuditAction.EDIT, actor=admin, metadata={"n": i})
    out = StringIO()
    call_command("verify_audit_chain", stdout=out)
    assert "OK (" in out.getvalue() and "BROKEN" not in out.getvalue()

    tamper("UPDATE audit_auditlog SET reason = 'edited' WHERE sequence = 2")
    out = StringIO()
    with pytest.raises(CommandError, match="failed verification"):
        call_command("verify_audit_chain", stdout=out)
    assert "BROKEN at sequence 2" in out.getvalue()
