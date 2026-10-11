import csv
import io
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditLog
from apps.departments.models import Department
from apps.devices.models import Device
from apps.lockdown.models import LockdownState
from apps.services_catalog.models import ServiceCatalog
from apps.vault.models import Credential

from .vault_helpers import OTHER_SECRET, STRONG_SECRET, create_credential

pytestmark = pytest.mark.django_db

REPORTS = "/api/v1/reports/"
FORMULA_TITLE = '=HYPERLINK("http://evil.example","x")'


def report(client, key, **params):
    return client.get(f"{REPORTS}{key}/", params)


@pytest.fixture
def data(client_for, employee, make_user, org, other_admin):
    """A small organization: two owners, a reused password, a weak key, a device, an audit trail."""
    ops = Department.objects.create(organization=org, name="Operations", code="OPS")
    employee.department = ops
    employee.save()
    colleague = make_user(full_name="Colin Colleague")
    github = ServiceCatalog.objects.create(organization=org, name="GitHub")

    first = create_credential(client_for(employee), title="Prod DB", service=str(github.id)).json()["id"]
    second = create_credential(client_for(colleague), title="Staging DB").json()["id"]  # same password: reuse
    weak = create_credential(client_for(colleague), title=FORMULA_TITLE, secret_type="API_KEY", password="abc").json()[
        "id"
    ]
    create_credential(client_for(other_admin), title="Foreign secret", password=OTHER_SECRET)  # other org
    Credential.objects.filter(pk=weak).update(expires_at=timezone.localdate() - timedelta(days=1))
    Device.objects.create(organization=org, user=employee, name="Laptop", token_hash="t" * 64, trust_state="TRUSTED")
    Device.objects.create(organization=org, user=colleague, name="Phone", token_hash="u" * 64, trust_state="PENDING")
    client_for(employee).post(f"/api/v1/vault/credentials/{first}/reveal/", {}, format="json")
    return {
        "employee": employee,
        "colleague": colleague,
        "ops": ops,
        "github": github,
        "first": first,
        "second": second,
        "weak": weak,
    }


def test_reports_are_for_security_staff_only(client_for, employee, sec_admin, admin):
    assert client_for(employee).get(REPORTS).status_code == 403
    assert report(client_for(employee), "audit").status_code == 403
    assert client_for(sec_admin).get(REPORTS).status_code == 200
    keys = {r["key"] for r in client_for(admin).get(REPORTS).json()["reports"]}
    assert keys == {"audit", "credentials", "devices", "shares", "lockdowns", "alerts"}


def test_no_report_or_export_contains_secret_material(client_for, sec_admin, data):
    client = client_for(sec_admin)
    stored = list(Credential.objects.values_list("secret_ciphertext", "blind_index"))
    forbidden = [STRONG_SECRET, OTHER_SECRET, "Plaintext-Marker"] + [v for pair in stored for v in pair]
    for key in ("audit", "credentials", "devices", "shares", "lockdowns", "alerts"):
        for fmt in ("json", "csv", "xlsx"):
            response = report(client, key, format=fmt)
            assert response.status_code == 200, (key, fmt)
            blob = response.content
            if fmt == "xlsx":
                sheet = load_workbook(io.BytesIO(blob)).active
                blob = " ".join(str(c.value) for row in sheet.iter_rows() for c in row).encode()
            for marker in forbidden:
                assert marker.encode() not in blob, (key, fmt, marker[:12])


def test_reports_never_include_other_organizations(client_for, sec_admin, data, other_admin):
    client = client_for(sec_admin)
    titles = [r["title"] for r in report(client, "credentials", page_size=200).json()["results"]]
    assert "Foreign secret" not in titles and "Prod DB" in titles
    actors = {r["actor_email"] for r in report(client, "audit", page_size=200).json()["results"]}
    assert other_admin.email not in actors and data["employee"].email in actors
    exported = report(client, "audit", format="csv").content.decode("utf-8-sig")
    assert "Foreign secret" not in exported and other_admin.email not in exported


def test_credential_hygiene_flags(client_for, sec_admin, data):
    client = client_for(sec_admin)

    def titles(**params):
        return sorted(r["title"] for r in report(client, "credentials", **params).json()["results"])

    assert titles(status="reused") == ["Prod DB", "Staging DB"]  # different owners, same secret
    assert titles(status="weak") == [FORMULA_TITLE]
    assert titles(status="expired") == [FORMULA_TITLE]
    assert titles(department=str(data["ops"].id)) == ["Prod DB"]
    assert titles(service=str(data["github"].id)) == ["Prod DB"]
    row = report(client, "credentials", resource=data["first"]).json()["results"][0]
    assert row["reuse_group_size"] == 2 and row["owner"] == data["employee"].full_name


def test_audit_trail_filters(client_for, sec_admin, data):
    client = client_for(sec_admin)
    reveals = report(client, "audit", action="REVEAL").json()
    assert reveals["count"] == 1 and reveals["results"][0]["actor_email"] == data["employee"].email
    assert report(client, "audit", action="REVEAL", user=str(data["colleague"].id)).json()["count"] == 0
    assert report(client, "audit", resource=data["first"], action="REVEAL").json()["count"] == 1
    assert report(client, "audit", service=str(data["github"].id), action="REVEAL").json()["count"] == 1
    assert report(client, "audit", department=str(data["ops"].id), action="REVEAL").json()["count"] == 1
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert report(client, "audit", date_from=tomorrow).json()["count"] == 0
    columns = report(client, "audit", columns="action,actor_email").json()
    assert [c["key"] for c in columns["columns"]] == ["action", "actor_email"]
    assert set(columns["results"][0]) == {"action", "actor_email"}


def test_audit_device_context_and_filter(client_for, sec_admin, data, rf):
    device = Device.objects.get(name="Laptop")
    audit.record(
        AuditAction.EDIT, actor=data["employee"], metadata={"device": {"id": str(device.pk), "trust": "TRUSTED"}}
    )
    rows = report(client_for(sec_admin), "audit", device_trust="TRUSTED").json()["results"]
    assert len(rows) == 1 and rows[0]["device_trust"] == "TRUSTED"


def test_device_share_and_lockdown_reports(client_for, sec_admin, data):
    client = client_for(sec_admin)
    assert [r["name"] for r in report(client, "devices", device_trust="PENDING").json()["results"]] == ["Phone"]
    client_for(data["employee"]).post(
        f"/api/v1/vault/credentials/{data['first']}/share/",
        {"grantee": str(data["colleague"].id), "permission": "VIEW"},
        format="json",
    )
    shares = report(client, "shares", share_status="active").json()["results"]
    assert len(shares) == 1 and shares[0]["grantee"] == data["colleague"].full_name and shares[0]["state"] == "ACTIVE"
    assert report(client, "shares", share_status="revoked").json()["count"] == 0
    LockdownState.objects.create(
        organization=data["employee"].organization,
        scope="GLOBAL",
        reason="Drill exercise",
        initiated_by=sec_admin,
        is_active=False,
    )
    incidents = report(client, "lockdowns", status="resolved").json()["results"]
    assert incidents[0]["reason"] == "Drill exercise" and incidents[0]["status"] == "resolved"


@pytest.mark.parametrize(
    "params,fragment",
    [
        ({"user": "not-an-id"}, "must be an id"),
        ({"date_from": "31/10/2026"}, "must be a date"),
        ({"date_from": "2026-10-31", "date_to": "2026-10-01"}, "must not be after"),
        ({"action": "STEAL"}, "Unknown action"),
        ({"status": "fabulous"}, "status must be one of"),
        ({"columns": "secret_ciphertext"}, "Unknown column"),
        ({"format": "docx"}, "format must be"),
    ],
)
def test_invalid_report_parameters_are_rejected(client_for, sec_admin, params, fragment):
    response = report(client_for(sec_admin), "audit", **params)
    assert response.status_code == 400
    assert fragment in response.json()["error"]["message"]


def test_filters_must_belong_to_the_report(client_for, sec_admin):
    response = report(client_for(sec_admin), "credentials", device_trust="TRUSTED")
    assert response.status_code == 400 and "device_trust" in response.json()["error"]["message"]
    assert report(client_for(sec_admin), "nope").status_code == 404


def test_custom_report_builder_uses_the_same_allow_list(client_for, sec_admin, data):
    client = client_for(sec_admin)
    ok = client.post(
        f"{REPORTS}custom/",
        {"dataset": "credentials", "columns": ["title", "strength"], "filters": {"status": "weak"}},
        format="json",
    )
    assert ok.status_code == 200 and ok.json()["results"] == [{"title": FORMULA_TITLE, "strength": "very_weak"}]
    sneaky = client.post(
        f"{REPORTS}custom/", {"dataset": "credentials", "columns": ["title", "secret_ciphertext"]}, format="json"
    )
    assert sneaky.status_code == 400
    assert (
        client.post(f"{REPORTS}custom/", {"dataset": "vault_keys", "columns": ["x"]}, format="json").status_code == 400
    )


# --------------------------------------------------------------------------- export formats


def test_csv_export_is_excel_friendly_and_neutralises_formulas(client_for, sec_admin, data):
    response = report(client_for(sec_admin), "credentials", format="csv")
    assert response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"].startswith('attachment; filename="securevault-credentials-')
    assert response["Cache-Control"] == "no-store"
    raw = response.content
    assert raw.startswith("﻿".encode()) and b"\r\n" in raw
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0][0] == "Credential"
    assert "'" + FORMULA_TITLE in [r[0] for r in rows[1:]]  # prefixed: opened in Excel it stays text
    entry = AuditLog.objects.get(action=AuditAction.REPORT_EXPORT)
    assert (
        entry.metadata["report"] == "credentials" and entry.metadata["format"] == "csv" and entry.metadata["rows"] == 3
    )


def test_xlsx_export_stores_formula_like_text_as_text(client_for, sec_admin, data):
    response = report(client_for(sec_admin), "credentials", format="xlsx", status="weak")
    sheet = load_workbook(io.BytesIO(response.content)).active
    cell = sheet["A2"]
    assert cell.value == FORMULA_TITLE and cell.data_type == "s"  # a string, not a formula
    assert sheet["A1"].value == "Credential" and sheet["A1"].font.bold


def test_pdf_export(client_for, sec_admin, data):
    response = report(client_for(sec_admin), "devices", format="pdf")
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-") and len(response.content) > 1000


def test_exports_are_capped_and_flag_truncation(client_for, sec_admin, data, settings):
    settings.REPORT_EXPORT_MAX_ROWS = 2
    response = report(client_for(sec_admin), "credentials", format="csv")
    assert response["X-Report-Truncated"] == "true"
    assert len(list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))) == 3  # header + 2
