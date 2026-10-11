import base64
import os
from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from apps.audit.models import AuditAction, AuditLog
from apps.vault import rotation
from apps.vault.models import Credential, OrganizationKey, SecureNote

from .vault_helpers import CREDENTIALS, NOTES, OTHER_SECRET, STRONG_SECRET, create_credential, create_note

pytestmark = pytest.mark.django_db


def new_key(version: int) -> str:
    return f"{version}:" + base64.urlsafe_b64encode(os.urandom(32)).decode()


def reveal(client, credential_id) -> str:
    return client.post(f"{CREDENTIALS}{credential_id}/reveal/", {}, format="json").json()["password"]


# --------------------------------------------------------------------------- KEK rotation


def test_rewrap_moves_data_keys_to_the_new_kek_so_the_old_one_can_be_retired(client_for, employee, settings):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    old_ring = settings.VAULT_KEK_KEYS
    assert OrganizationKey.objects.get(organization=employee.organization).kek_version == 1

    settings.VAULT_KEK_KEYS = f"{old_ring},{new_key(2)}"  # operator adds KEK v2 alongside v1
    assert rotation.rewrap_data_keys() == 1
    row = OrganizationKey.objects.get(organization=employee.organization)
    assert row.kek_version == 2 and row.wrapped_key.startswith("v2:")
    assert rotation.rewrap_data_keys() == 0  # nothing left to do

    settings.VAULT_KEK_KEYS = settings.VAULT_KEK_KEYS.split(",", 1)[1]  # operator retires KEK v1
    assert reveal(client, credential_id) == STRONG_SECRET
    assert AuditLog.objects.filter(action=AuditAction.KEY_ROTATION, metadata__operation="rewrap").count() == 1


def test_without_rewrap_retiring_the_old_kek_loses_access(client_for, employee, settings):
    """Documents why --rewrap-keks must run before a KEK is removed."""
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    settings.VAULT_KEK_KEYS = new_key(2)  # v1 removed, nothing re-wrapped
    response = client.post(f"{CREDENTIALS}{credential_id}/reveal/", {}, format="json")
    assert response.status_code == 500 and response.json()["error"]["code"] == "decryption_failed"


# --------------------------------------------------------------------------- DEK rotation


def test_data_key_rotation_reencrypts_everything_and_preserves_plaintext(client_for, employee):
    client = client_for(employee)
    ids = [create_credential(client, title=f"C{i}", password=f"Rot4te-Me-{i}-Secret!").json()["id"] for i in range(3)]
    note_id = create_note(client).json()["id"]
    client.delete(f"{CREDENTIALS}{ids[2]}/")  # archived items are re-encrypted too
    before = {str(c.pk): c.secret_ciphertext for c in Credential.objects.all()}

    moved = rotation.rotate_data_key(employee.organization)
    assert moved == 4  # 3 credentials + 1 note

    keys = OrganizationKey.objects.filter(organization=employee.organization).order_by("version")
    assert [(k.version, k.status) for k in keys] == [(1, "RETIRED"), (2, "ACTIVE")]
    assert keys[0].retired_at is not None
    assert {c.key_version for c in Credential.objects.all()} == {2} and SecureNote.objects.get().key_version == 2
    assert all(c.secret_ciphertext != before[str(c.pk)] for c in Credential.objects.all())
    assert [reveal(client, i) for i in ids[:2]] == ["Rot4te-Me-0-Secret!", "Rot4te-Me-1-Secret!"]
    assert client.post(f"{NOTES}{note_id}/reveal/", {}, format="json").json()["content"].startswith("root token")
    entry = AuditLog.objects.get(action=AuditAction.KEY_ROTATION, metadata__operation="rotate_data_key")
    assert entry.metadata == {"operation": "rotate_data_key", "from_version": 1, "to_version": 2}


def test_new_records_use_the_new_key_after_rotation(client_for, employee):
    client = client_for(employee)
    create_credential(client, title="Before")
    rotation.rotate_data_key(employee.organization)
    after = create_credential(client, title="After").json()["id"]
    assert Credential.objects.get(pk=after).key_version == 2
    assert reveal(client, after) == STRONG_SECRET


def test_an_interrupted_rotation_leaves_everything_readable(client_for, employee):
    client = client_for(employee)
    ids = [create_credential(client, title=f"C{i}").json()["id"] for i in range(3)]

    from apps.vault import encryption

    real_seal = encryption.seal
    calls = {"n": 0}

    def flaky_seal(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("process killed mid-rotation")
        return real_seal(*args, **kwargs)

    with mock.patch("apps.vault.rotation.encryption.seal", side_effect=flaky_seal), pytest.raises(RuntimeError):
        rotation.rotate_data_key(employee.organization)

    assert {c.key_version for c in Credential.objects.all()} == {1, 2}  # mixed state
    assert all(reveal(client, i) == STRONG_SECRET for i in ids)  # old key row is kept, so all still decrypt

    rotation.rotate_data_key(employee.organization)  # operator simply re-runs
    assert {c.key_version for c in Credential.objects.all()} == {3}
    assert all(reveal(client, i) == STRONG_SECRET for i in ids)


def test_rotation_never_touches_other_organizations(client_for, employee, other_admin):
    create_credential(client_for(employee))
    foreign = create_credential(client_for(other_admin)).json()["id"]
    foreign_before = Credential.objects.get(pk=foreign)
    rotation.rotate_data_key(employee.organization)
    foreign_after = Credential.objects.get(pk=foreign)
    assert foreign_after.secret_ciphertext == foreign_before.secret_ciphertext and foreign_after.key_version == 1
    assert OrganizationKey.objects.get(organization=other_admin.organization).status == "ACTIVE"


# --------------------------------------------------------------------------- blind index rotation


def test_reindex_moves_blind_indexes_to_the_new_key_and_keeps_reuse_detection(client_for, employee, settings):
    client = client_for(employee)
    a = create_credential(client, title="A").json()["id"]
    b = create_credential(client, title="B").json()["id"]
    c = create_credential(client, title="C", password=OTHER_SECRET).json()["id"]
    old = {x: Credential.objects.get(pk=x).blind_index for x in (a, b, c)}

    settings.VAULT_BLIND_INDEX_KEYS = f"{settings.VAULT_BLIND_INDEX_KEYS},{new_key(2)}"
    assert rotation.reindex_blind_indexes() == 3
    assert rotation.reindex_blind_indexes() == 0

    new = {x: Credential.objects.get(pk=x) for x in (a, b, c)}
    assert {x.blind_index_version for x in new.values()} == {2}
    assert all(new[x].blind_index != old[x] for x in (a, b, c))
    assert new[a].blind_index == new[b].blind_index != new[c].blind_index
    assert client.get(f"{CREDENTIALS}{a}/").json()["reuse_count"] == 1


# --------------------------------------------------------------------------- management command


def test_command_requires_an_operation():
    with pytest.raises(CommandError, match="Choose at least one"):
        call_command("rotate_vault_keys")


def test_command_rotates_one_organization(client_for, employee, other_admin, capsys):
    create_credential(client_for(employee))
    create_credential(client_for(other_admin))
    call_command("rotate_vault_keys", "--rotate-deks", "--org", employee.organization.slug)
    assert "re-encrypted 1 record(s)" in capsys.readouterr().out
    assert OrganizationKey.objects.get(organization=employee.organization, status="ACTIVE").version == 2
    assert OrganizationKey.objects.get(organization=other_admin.organization, status="ACTIVE").version == 1
    with pytest.raises(CommandError, match="No organization"):
        call_command("rotate_vault_keys", "--rotate-deks", "--org", "does-not-exist")


def test_purge_command_runs(capsys):
    call_command("purge_archived_vault_items")
    assert "Purged 0 item(s)" in capsys.readouterr().out
