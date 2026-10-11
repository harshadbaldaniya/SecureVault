from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.policies.models import policy_for
from apps.services_catalog.models import ServiceCatalog
from apps.vault.models import Credential

from .vault_helpers import CREDENTIALS, OTHER_SECRET, STRONG_SECRET, create_credential, dump_database_text

pytestmark = pytest.mark.django_db


def detail(credential_id: str) -> str:
    return f"{CREDENTIALS}{credential_id}/"


# --------------------------------------------------------------------------- create / validation


def test_create_returns_metadata_but_never_the_secret(client_for, employee):
    response = create_credential(client_for(employee), category="Production", tags=["DB", " prod "])
    assert response.status_code == 201
    body = response.json()
    assert "password" not in body and STRONG_SECRET not in response.content.decode()
    assert body["tags"] == ["db", "prod"]
    assert body["owner_name"] == employee.full_name
    assert body["strength"] in {"fair", "strong", "very_strong"}
    assert body["entropy_bits"] > 60
    assert body["permissions"] == ["COPY", "DELETE", "EDIT", "REVEAL", "SHARE", "VIEW"]
    assert Credential.objects.get(pk=body["id"]).owner_id == employee.id


def test_password_is_required_on_create(client_for, employee):
    response = client_for(employee).post(CREDENTIALS, {"title": "No secret"}, format="json")
    assert response.status_code == 400
    assert "password" in response.json()["error"]["details"]


def test_policy_complexity_is_enforced_for_passwords_only(client_for, employee):
    client = client_for(employee)
    weak = create_credential(client, password="short")
    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "policy_violation"
    problems = " ".join(weak.json()["error"]["details"]["password"])
    assert "at least 14" in problems and "uppercase" in problems and "number" in problems and "symbol" in problems

    # Machine-generated API keys are exempt from human-password complexity rules.
    api_key = create_credential(client, title="CI token", secret_type="API_KEY", password="ghp_abcdef0123456789")
    assert api_key.status_code == 201


def test_policy_changes_apply_to_new_credentials(client_for, employee):
    policy = policy_for(employee.organization)
    policy.min_password_length = 30
    policy.save()
    assert create_credential(client_for(employee)).status_code == 400


def test_expiry_defaults_from_policy_max_age(client_for, employee):
    body = create_credential(client_for(employee)).json()
    assert body["expires_at"] == str(timezone.localdate() + timedelta(days=90))

    policy = policy_for(employee.organization)
    policy.max_password_age_days = 0
    policy.save()
    assert create_credential(client_for(employee), title="No expiry").json()["expires_at"] is None


def test_past_expiry_is_rejected_but_old_expired_items_stay_editable(client_for, employee):
    client = client_for(employee)
    past = str(timezone.localdate() - timedelta(days=1))
    assert create_credential(client, expires_at=past).status_code == 400

    credential_id = create_credential(client).json()["id"]
    Credential.objects.filter(pk=credential_id).update(expires_at=timezone.localdate() - timedelta(days=5))
    assert client.patch(detail(credential_id), {"title": "Renamed"}, format="json").status_code == 200
    body = client.get(detail(credential_id)).json()
    assert body["is_expired"] is True


@pytest.mark.parametrize("tags", [["bad/tag"], ["x" * 41], [f"t{i}" for i in range(21)], ["ok", "$$$"]])
def test_invalid_tags_are_rejected(client_for, employee, tags):
    assert create_credential(client_for(employee), tags=tags).status_code == 400


def test_service_must_belong_to_the_organization_and_be_active(client_for, employee, other_org, org):
    foreign = ServiceCatalog.objects.create(organization=other_org, name="Foreign")
    inactive = ServiceCatalog.objects.create(organization=org, name="Retired", status="INACTIVE")
    good = ServiceCatalog.objects.create(organization=org, name="GitHub")
    client = client_for(employee)
    assert create_credential(client, service=str(foreign.id)).status_code == 400
    assert create_credential(client, service=str(inactive.id)).status_code == 400
    ok = create_credential(client, service=str(good.id))
    assert ok.status_code == 201 and ok.json()["service_name"] == "GitHub"


# --------------------------------------------------------------------------- visibility (zero trust)


def test_users_only_see_their_own_credentials(client_for, employee, make_user):
    mine = create_credential(client_for(employee), title="Mine").json()["id"]
    colleague = make_user()
    theirs = create_credential(client_for(colleague), title="Theirs").json()["id"]
    client = client_for(employee)

    titles = [c["title"] for c in client.get(CREDENTIALS).json()["results"]]
    assert titles == ["Mine"]
    assert client.get(detail(mine)).status_code == 200
    assert client.get(detail(theirs)).status_code == 404


def test_administrators_do_not_get_access_to_other_peoples_secrets(client_for, admin, sec_admin, employee):
    credential_id = create_credential(client_for(employee)).json()["id"]
    for user in (admin, sec_admin):
        client = client_for(user)
        assert client.get(CREDENTIALS).json()["count"] == 0
        assert client.get(detail(credential_id)).status_code == 404
        assert client.post(f"{detail(credential_id)}reveal/", {}, format="json").status_code == 404
        assert client.patch(detail(credential_id), {"title": "hijack"}, format="json").status_code == 404
        assert client.delete(detail(credential_id)).status_code == 404
    assert Credential.objects.get(pk=credential_id).title == "Prod DB"


def test_other_organizations_credentials_are_invisible(client_for, employee, other_admin):
    credential_id = create_credential(client_for(other_admin)).json()["id"]
    client = client_for(employee)
    assert client.get(CREDENTIALS).json()["count"] == 0
    assert client.get(detail(credential_id)).status_code == 404
    assert client.post(f"{detail(credential_id)}reveal/", {}, format="json").status_code == 404


def test_probing_someone_elses_credential_is_audited_as_denied(client_for, employee, make_user):
    colleague = make_user()
    credential_id = create_credential(client_for(colleague)).json()["id"]
    response = client_for(employee).post(f"{detail(credential_id)}reveal/", {}, format="json")
    assert response.status_code == 404  # same answer as a nonexistent id: no existence leak
    probe = AuditLog.objects.get(action=AuditAction.REVEAL, outcome=AuditOutcome.DENIED)
    assert probe.actor_id == employee.id and probe.target_id == credential_id and probe.reason == "not_visible"


def test_probing_a_nonexistent_or_malformed_id_is_not_an_error(client_for, employee):
    client = client_for(employee)
    missing = f"{CREDENTIALS}00000000-0000-0000-0000-000000000000/reveal/"
    assert client.post(missing, {}, format="json").status_code == 404
    assert client.post(f"{CREDENTIALS}not-a-uuid/reveal/", {}, format="json").status_code == 404
    assert not AuditLog.objects.filter(outcome=AuditOutcome.DENIED).exists()


def test_anonymous_requests_are_refused(anon):
    assert anon.get(CREDENTIALS).status_code == 401


# --------------------------------------------------------------------------- reveal


def test_reveal_returns_the_secret_uncached_and_audits_without_it(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    response = client.post(f"{detail(credential_id)}reveal/", {}, format="json")
    assert response.status_code == 200
    assert response.json() == {"password": STRONG_SECRET}
    assert response["Cache-Control"] == "no-store"

    entry = AuditLog.objects.get(action=AuditAction.REVEAL, outcome=AuditOutcome.SUCCESS)
    assert entry.actor_id == employee.id and entry.target_id == credential_id
    assert entry.metadata == {"purpose": "view"}
    assert STRONG_SECRET not in " ".join(str(r) for r in AuditLog.objects.values_list())


def test_copy_purpose_is_recorded_as_copy(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    assert client.post(f"{detail(credential_id)}reveal/", {"purpose": "copy"}, format="json").status_code == 200
    assert AuditLog.objects.filter(action=AuditAction.COPY, outcome=AuditOutcome.SUCCESS).count() == 1
    assert not AuditLog.objects.filter(action=AuditAction.REVEAL).exists()


def test_invalid_reveal_purpose_is_rejected(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    assert client.post(f"{detail(credential_id)}reveal/", {"purpose": "email-it"}, format="json").status_code == 400


def test_reveal_requires_post_so_secrets_never_travel_in_cacheable_gets(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    assert client.get(f"{detail(credential_id)}reveal/").status_code == 405


def test_reveal_is_refused_if_the_audit_record_cannot_be_written(client_for, employee):
    from unittest import mock

    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    with mock.patch("apps.audit.services._append", side_effect=RuntimeError("audit down")):
        response = client.post(f"{detail(credential_id)}reveal/", {}, format="json")
    assert response.status_code == 500
    assert STRONG_SECRET not in response.content.decode()


def test_reveal_is_rate_limited_per_user(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    statuses = [client.post(f"{detail(credential_id)}reveal/", {}, format="json").status_code for _ in range(32)]
    assert statuses[:30] == [200] * 30
    assert 429 in statuses[30:]


# --------------------------------------------------------------------------- edit


def test_metadata_edit_leaves_the_ciphertext_untouched(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    before = Credential.objects.get(pk=credential_id)
    response = client.patch(detail(credential_id), {"title": "Renamed", "tags": ["x"]}, format="json")
    assert response.status_code == 200
    after = Credential.objects.get(pk=credential_id)
    assert after.title == "Renamed" and after.secret_ciphertext == before.secret_ciphertext
    assert after.password_changed_at == before.password_changed_at


def test_changing_the_password_reencrypts_and_renews_expiry(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    Credential.objects.filter(pk=credential_id).update(
        expires_at=timezone.localdate() + timedelta(days=2), password_changed_at=timezone.now() - timedelta(days=60)
    )
    before = Credential.objects.get(pk=credential_id)

    response = client.patch(detail(credential_id), {"password": OTHER_SECRET}, format="json")
    assert response.status_code == 200
    after = Credential.objects.get(pk=credential_id)
    assert after.secret_ciphertext != before.secret_ciphertext
    assert after.blind_index != before.blind_index
    assert after.password_changed_at > before.password_changed_at
    assert after.expires_at == timezone.localdate() + timedelta(days=90)
    assert client.post(f"{detail(credential_id)}reveal/", {}, format="json").json() == {"password": OTHER_SECRET}

    edit = AuditLog.objects.filter(action=AuditAction.EDIT).latest("id")
    assert edit.metadata == {"changed": ["password"]}  # the field name, never the value
    assert OTHER_SECRET not in dump_database_text()


def test_a_weak_replacement_password_is_rejected_and_nothing_changes(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    before = Credential.objects.get(pk=credential_id).secret_ciphertext
    assert client.patch(detail(credential_id), {"password": "weak"}, format="json").status_code == 400
    assert Credential.objects.get(pk=credential_id).secret_ciphertext == before


def test_owner_cannot_be_reassigned_through_the_api(client_for, employee, make_user):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    other = make_user()
    attempt = {"owner": str(other.id), "organization": str(other.organization_id)}
    client.patch(detail(credential_id), attempt, format="json")
    assert Credential.objects.get(pk=credential_id).owner_id == employee.id


# --------------------------------------------------------------------------- archive / retention


def test_delete_archives_and_restore_brings_it_back(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]

    assert client.delete(detail(credential_id)).status_code == 204
    assert client.get(CREDENTIALS).json()["count"] == 0
    archived = client.get(CREDENTIALS, {"archived": "true"}).json()
    assert [c["id"] for c in archived["results"]] == [credential_id]
    assert Credential.objects.filter(pk=credential_id).exists()  # still stored, still encrypted

    restored = client.post(f"{detail(credential_id)}restore/")
    assert restored.status_code == 200 and restored.json()["archived_at"] is None
    assert client.get(CREDENTIALS).json()["count"] == 1


def test_archived_items_cannot_be_revealed_or_edited(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    client.delete(detail(credential_id))
    reveal = client.post(f"{detail(credential_id)}reveal/", {}, format="json")
    assert reveal.status_code == 409 and reveal.json()["error"]["code"] == "archived"
    assert client.patch(detail(credential_id), {"title": "x"}, format="json").status_code == 409


def test_purge_removes_only_items_past_the_retention_period(client_for, employee):
    from apps.vault.services import purge_expired_archives

    client = client_for(employee)
    old = create_credential(client, title="Old").json()["id"]
    recent = create_credential(client, title="Recent").json()["id"]
    live = create_credential(client, title="Live").json()["id"]
    client.delete(detail(old))
    client.delete(detail(recent))
    Credential.objects.filter(pk=old).update(archived_at=timezone.now() - timedelta(days=31))
    Credential.objects.filter(pk=recent).update(archived_at=timezone.now() - timedelta(days=29))

    assert purge_expired_archives() == 1
    assert set(Credential.objects.values_list("title", flat=True)) == {"Recent", "Live"}
    purge = AuditLog.objects.get(action=AuditAction.DELETE, metadata__purged=True)
    assert purge.target_id == old and purge.organization_id == employee.organization_id
    assert live  # untouched


# --------------------------------------------------------------------------- search and hygiene


def test_search_covers_metadata_only_never_secrets(client_for, employee):
    client = client_for(employee)
    github = ServiceCatalog.objects.create(organization=employee.organization, name="GitHub")
    create_credential(client, title="Deploy bot", username="ci-robot", service=str(github.id), tags=["ci"])
    create_credential(client, title="Other", username="alice", password=OTHER_SECRET)

    def found(term):
        return [c["title"] for c in client.get(CREDENTIALS, {"search": term}).json()["results"]]

    assert found("deploy") == ["Deploy bot"]  # title
    assert found("robot") == ["Deploy bot"]  # username
    assert found("github") == ["Deploy bot"]  # service name
    assert found("Plaintext-Marker") == []  # a fragment of the stored secret: not searchable
    assert found(STRONG_SECRET) == []
    assert found("%") == []  # wildcard characters are matched literally


def test_filters_by_tag_category_and_service(client_for, employee):
    client = client_for(employee)
    create_credential(client, title="A", tags=["prod", "db"], category="Production")
    create_credential(client, title="B", tags=["dev"], category="Staging")
    ids = lambda params: [c["title"] for c in client.get(CREDENTIALS, params).json()["results"]]  # noqa: E731
    assert ids({"tag": "PROD"}) == ["A"]
    assert ids({"category": "Staging"}) == ["B"]


def test_expiry_filters_and_flags(client_for, employee):
    client = client_for(employee)
    today = timezone.localdate()
    expired = create_credential(client, title="Expired").json()["id"]
    soon = create_credential(client, title="Soon", expires_at=str(today + timedelta(days=5))).json()["id"]
    create_credential(client, title="Later", expires_at=str(today + timedelta(days=200)))
    Credential.objects.filter(pk=expired).update(expires_at=today - timedelta(days=1))

    titles = lambda params: sorted(c["title"] for c in client.get(CREDENTIALS, params).json()["results"])  # noqa: E731
    assert titles({"expired": "true"}) == ["Expired"]
    assert titles({"expiring_within_days": 14}) == ["Soon"]
    assert client.get(detail(soon)).json()["expires_soon"] is True
    assert client.get(detail(expired)).json()["is_expired"] is True


def test_reuse_is_detected_from_blind_indexes_among_your_own_active_credentials(client_for, employee, make_user):
    client = client_for(employee)
    a = create_credential(client, title="A").json()["id"]
    b = create_credential(client, title="B").json()["id"]
    c = create_credential(client, title="C", password=OTHER_SECRET).json()["id"]
    create_credential(client_for(make_user()), title="Colleague's, same password")  # not visible, not counted

    by_id = {x["id"]: x for x in client.get(CREDENTIALS).json()["results"]}
    assert by_id[a]["reuse_count"] == 1 and by_id[b]["reuse_count"] == 1 and by_id[c]["reuse_count"] == 0
    assert [x["title"] for x in client.get(CREDENTIALS, {"reused": "true"}).json()["results"]] == ["A", "B"]

    client.delete(detail(b))  # archived duplicates stop counting
    assert client.get(detail(a)).json()["reuse_count"] == 0


# --------------------------------------------------------------------------- the authorization gate


@pytest.mark.parametrize(
    "method,suffix,payload",
    [
        ("post", "reveal/", {}),
        ("post", "reveal/", {"purpose": "copy"}),
        ("patch", "", {"title": "x"}),
        ("delete", "", None),
    ],
)
def test_every_sensitive_action_runs_the_zero_trust_gate(client_for, employee, monkeypatch, method, suffix, payload):
    """Later phases register device-trust / anomaly / lockdown checks; they must reach all of these actions."""
    from rest_framework.exceptions import PermissionDenied

    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    seen = []

    def deny(ctx):
        seen.append(ctx.action)
        raise PermissionDenied("blocked by a registered check", code="blocked")

    monkeypatch.setattr("core.access_gate._sensitive_checks", [deny])
    response = getattr(client, method)(f"{detail(credential_id)}{suffix}", payload, format="json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "blocked"
    assert len(seen) == 1
    unchanged = Credential.objects.get(pk=credential_id)
    assert unchanged.title == "Prod DB" and not unchanged.is_archived
    assert STRONG_SECRET not in response.content.decode()


def test_restore_also_runs_the_gate(client_for, employee, monkeypatch):
    from rest_framework.exceptions import PermissionDenied

    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    client.delete(detail(credential_id))

    def deny(ctx):
        raise PermissionDenied("blocked", code="blocked")

    monkeypatch.setattr("core.access_gate._sensitive_checks", [deny])
    assert client.post(f"{detail(credential_id)}restore/").status_code == 403
    assert Credential.objects.get(pk=credential_id).is_archived


def test_gate_denies_when_the_account_or_organization_is_no_longer_active(employee):
    from rest_framework.exceptions import PermissionDenied

    from core.access_gate import Action, authorize

    credential = Credential(organization=employee.organization, owner=employee, title="x")
    credential.organization.status = "SUSPENDED"
    with pytest.raises(PermissionDenied):
        authorize(employee, credential, Action.REVEAL)


def test_gate_denial_persists_a_denied_audit_record(employee, make_user):
    from rest_framework.exceptions import PermissionDenied

    from core.access_gate import Action, authorize

    other = make_user()
    credential = Credential(organization=employee.organization, owner=other, title="not yours")
    with pytest.raises(PermissionDenied):
        authorize(employee, credential, Action.REVEAL)
    entry = AuditLog.objects.get(action=AuditAction.REVEAL, outcome=AuditOutcome.DENIED)
    assert entry.actor_id == employee.id and entry.reason == "permission_denied"
