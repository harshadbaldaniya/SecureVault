import pytest

from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.vault.models import SecureNote

from .vault_helpers import NOTES, create_note, dump_database_text

pytestmark = pytest.mark.django_db

BODY = "root token: s3cr3t-note-body-8841"


def detail(note_id: str) -> str:
    return f"{NOTES}{note_id}/"


def test_note_content_is_encrypted_and_never_returned_by_reads(client_for, employee):
    client = client_for(employee)
    response = create_note(client, tags=["Ops"], category="Runbooks")
    assert response.status_code == 201
    note_id = response.json()["id"]
    assert "content" not in response.json() and BODY not in response.content.decode()
    assert response.json()["tags"] == ["ops"]

    assert "s3cr3t-note-body-8841" not in dump_database_text()
    assert BODY not in client.get(NOTES).content.decode() + client.get(detail(note_id)).content.decode()
    row = SecureNote.objects.get(pk=note_id)
    assert row.secret_ciphertext.startswith("v1:") and BODY not in row.secret_ciphertext


def test_reveal_returns_content_with_no_store_and_audits_without_it(client_for, employee):
    client = client_for(employee)
    note_id = create_note(client).json()["id"]
    response = client.post(f"{detail(note_id)}reveal/", {}, format="json")
    assert response.json() == {"content": BODY}
    assert response["Cache-Control"] == "no-store"
    entry = AuditLog.objects.get(action=AuditAction.REVEAL, outcome=AuditOutcome.SUCCESS)
    assert entry.target_type == "note"
    assert "s3cr3t" not in " ".join(str(r) for r in AuditLog.objects.values_list())


def test_content_is_required_and_size_limited(client_for, employee):
    client = client_for(employee)
    assert client.post(NOTES, {"title": "Empty"}, format="json").status_code == 400
    assert create_note(client, content="x" * 65_537).status_code == 400
    assert create_note(client, content="x" * 65_536).status_code == 201


def test_update_reencrypts_only_when_content_changes(client_for, employee):
    client = client_for(employee)
    note_id = create_note(client).json()["id"]
    before = SecureNote.objects.get(pk=note_id).secret_ciphertext

    client.patch(detail(note_id), {"title": "New title"}, format="json")
    assert SecureNote.objects.get(pk=note_id).secret_ciphertext == before

    client.patch(detail(note_id), {"content": "replacement body"}, format="json")
    assert SecureNote.objects.get(pk=note_id).secret_ciphertext != before
    assert client.post(f"{detail(note_id)}reveal/", {}, format="json").json() == {"content": "replacement body"}


def test_notes_are_private_to_their_owner(client_for, employee, admin, other_admin):
    note_id = create_note(client_for(employee)).json()["id"]
    for user in (admin, other_admin):
        client = client_for(user)
        assert client.get(NOTES).json()["count"] == 0
        assert client.get(detail(note_id)).status_code == 404
        assert client.post(f"{detail(note_id)}reveal/", {}, format="json").status_code == 404
        assert client.delete(detail(note_id)).status_code == 404
    # Only the same-organization admin's attempts are probes (3 sensitive calls); a foreign organization
    # cannot even tell the note exists, so nothing is recorded for it.
    assert AuditLog.objects.filter(outcome=AuditOutcome.DENIED, target_type="note").count() == 2


def test_note_archive_restore_and_reveal_rules(client_for, employee):
    client = client_for(employee)
    note_id = create_note(client).json()["id"]
    assert client.delete(detail(note_id)).status_code == 204
    assert client.post(f"{detail(note_id)}reveal/", {}, format="json").status_code == 409
    assert client.post(f"{detail(note_id)}restore/").status_code == 200
    assert client.post(f"{detail(note_id)}reveal/", {}, format="json").status_code == 200


def test_note_search_and_filters_use_metadata_only(client_for, employee):
    client = client_for(employee)
    create_note(client, title="Kubernetes runbook", category="Ops", tags=["k8s"])
    create_note(client, title="Licence key", content="LIC-ABCD-1234")
    titles = lambda params: [n["title"] for n in client.get(NOTES, params).json()["results"]]  # noqa: E731
    assert titles({"search": "kubernetes"}) == ["Kubernetes runbook"]
    assert titles({"tag": "k8s"}) == ["Kubernetes runbook"]
    assert titles({"search": "LIC-ABCD"}) == []  # content is not searchable
