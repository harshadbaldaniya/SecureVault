import base64

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from apps.audit.models import AuditAction, AuditLog, AuditOutcome
from apps.vault import encryption
from apps.vault.keys import EnvKeyProvider, validate_key_separation
from apps.vault.models import Credential, OrganizationKey
from core.crypto import b64d

from .vault_helpers import OTHER_SECRET, STRONG_SECRET, create_credential, create_note, dump_database_text

pytestmark = pytest.mark.django_db


def stored_row(credential_id: str) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM vault_credential WHERE id = %s", [credential_id])
        columns = [c.name for c in cursor.description]
        return dict(zip(columns, cursor.fetchone(), strict=True))


# --------------------------------------------------------------------------- encrypted at rest


def test_plaintext_secret_is_stored_nowhere_in_the_database(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    note_id = create_note(client).json()["id"]
    client.post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {}, format="json")
    client.post(f"/api/v1/vault/notes/{note_id}/reveal/", {}, format="json")
    client.patch(f"/api/v1/vault/credentials/{credential_id}/", {"password": OTHER_SECRET}, format="json")

    dump = dump_database_text()
    for marker in (STRONG_SECRET, OTHER_SECRET, "s3cr3t-note-body-8841", "Plaintext-Marker", "Another-Marker"):
        assert marker not in dump, f"{marker!r} leaked into the database"


def test_database_scan_would_catch_plaintext(client_for, employee):
    """Negative control: the scan above is only meaningful if it finds a marker when one IS stored."""
    create_credential(client_for(employee), title="control-marker-in-a-plaintext-title")
    assert "control-marker-in-a-plaintext-title" in dump_database_text()


def test_stored_row_holds_only_ciphertext_and_metadata(client_for, employee):
    credential_id = create_credential(client_for(employee), title="Billing DB", username="billing").json()["id"]
    row = stored_row(credential_id)

    assert row["title"] == "Billing DB" and row["username"] == "billing"  # plaintext metadata by design
    version, nonce, ciphertext = row["secret_ciphertext"].split(":")
    assert version == "v1"
    assert len(b64d(nonce)) == 12  # fresh 12-byte IV
    assert len(b64d(ciphertext)) == len(STRONG_SECRET) + 16  # ciphertext + 16-byte GCM tag
    assert STRONG_SECRET not in " ".join(str(v) for v in row.values())
    assert row["key_version"] == 1
    assert len(row["blind_index"]) == 64


def test_every_encryption_uses_a_fresh_nonce_and_ciphertext(client_for, employee):
    client = client_for(employee)
    ids = [create_credential(client, title=f"Same {i}").json()["id"] for i in range(5)]
    tokens = [stored_row(i)["secret_ciphertext"] for i in ids]
    nonces = {t.split(":")[1] for t in tokens}
    assert len(set(tokens)) == 5 and len(nonces) == 5  # same password, five different ciphertexts


def test_ciphertext_is_bound_to_its_record(client_for, employee):
    """Moving a valid ciphertext into another record must fail authentication (AAD binding)."""
    client = client_for(employee)
    a = create_credential(client, title="A", password=STRONG_SECRET).json()["id"]
    b = create_credential(client, title="B", password=OTHER_SECRET).json()["id"]
    Credential.objects.filter(pk=b).update(secret_ciphertext=Credential.objects.get(pk=a).secret_ciphertext)

    response = client.post(f"/api/v1/vault/credentials/{b}/reveal/", {}, format="json")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "decryption_failed"
    assert STRONG_SECRET not in response.content.decode()
    failure = AuditLog.objects.get(action=AuditAction.REVEAL, outcome=AuditOutcome.FAILURE)
    assert failure.reason == "decryption_failed"


def test_tampered_ciphertext_is_rejected(client_for, employee):
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    credential = Credential.objects.get(pk=credential_id)
    version, nonce, ciphertext = credential.secret_ciphertext.split(":")
    flipped = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    Credential.objects.filter(pk=credential_id).update(secret_ciphertext=f"{version}:{nonce}:{flipped}")

    response = client.post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {}, format="json")
    assert response.json()["error"]["code"] == "decryption_failed"


def test_ciphertext_is_bound_to_the_organization(client_for, employee, make_user, other_org):
    """A foreign organization's key cannot open another organization's ciphertext, and vice versa."""
    credential_id = create_credential(client_for(employee)).json()["id"]
    credential = Credential.objects.get(pk=credential_id)
    from core.crypto import DecryptionError

    encryption.active_key(other_org)  # other org has its own data key
    with pytest.raises(DecryptionError):
        encryption.open_sealed(other_org.pk, "credential", credential.pk, "password", credential.secret_ciphertext, 1)


# --------------------------------------------------------------------------- keys


def test_data_key_is_stored_only_wrapped(client_for, employee):
    create_credential(client_for(employee))
    row = OrganizationKey.objects.get(organization=employee.organization)
    dek = EnvKeyProvider().unwrap(row.wrapped_key, encryption._dek_aad(row.organization_id, row.version))
    assert len(dek) == 32
    dump = dump_database_text()
    assert base64.urlsafe_b64encode(dek).decode().rstrip("=") not in dump
    assert dek.hex() not in dump
    assert row.kek_version == 1 and row.wrapped_key.startswith("v1:")


def test_each_organization_gets_its_own_data_key(client_for, employee, other_admin):
    create_credential(client_for(employee))
    create_credential(client_for(other_admin))
    wrapped = list(OrganizationKey.objects.values_list("wrapped_key", flat=True))
    assert len(wrapped) == 2 and len(set(wrapped)) == 2
    provider = EnvKeyProvider()
    deks = {
        provider.unwrap(k.wrapped_key, encryption._dek_aad(k.organization_id, k.version))
        for k in OrganizationKey.objects.all()
    }
    assert len(deks) == 2


def test_only_one_active_key_per_organization(employee):
    first = encryption.active_key(employee.organization)
    assert encryption.active_key(employee.organization).pk == first.pk
    assert OrganizationKey.objects.filter(organization=employee.organization).count() == 1


def test_blind_index_is_deterministic_per_organization_and_not_the_encryption_key(client_for, employee, other_admin):
    a1 = create_credential(client_for(employee), title="One").json()["id"]
    a2 = create_credential(client_for(employee), title="Two").json()["id"]
    b1 = create_credential(client_for(other_admin), title="Other org").json()["id"]
    index = {i: stored_row(i)["blind_index"] for i in (a1, a2, b1)}
    assert index[a1] == index[a2]  # same org + same secret: equal (this is the reuse signal)
    assert index[a1] != index[b1]  # other org: unlinkable
    assert STRONG_SECRET not in index[a1]


def test_vault_works_through_the_key_provider_interface(client_for, employee, settings):
    settings.VAULT_KEY_PROVIDER = "tests.fake_provider.CountingProvider"
    from tests.fake_provider import CountingProvider

    CountingProvider.calls.clear()
    client = client_for(employee)
    credential_id = create_credential(client).json()["id"]
    client.post(f"/api/v1/vault/credentials/{credential_id}/reveal/", {}, format="json")
    assert {"wrap", "blind_index", "unwrap"} <= set(CountingProvider.calls)


@pytest.mark.parametrize(
    "overrides",
    [
        {"VAULT_BLIND_INDEX_KEYS": "same"},  # blind index key equal to a KEK
        {"MFA_ENCRYPTION_KEYS": "same"},  # MFA key equal to a KEK
    ],
)
def test_key_purposes_must_not_share_material(settings, overrides):
    shared = settings.VAULT_KEK_KEYS
    for name, value in overrides.items():
        setattr(settings, name, shared if value == "same" else value)
    with pytest.raises(ImproperlyConfigured, match="must not share key material"):
        validate_key_separation()


def test_missing_or_malformed_keyring_fails_loudly(settings):
    settings.VAULT_KEK_KEYS = "1:not-a-32-byte-key"
    with pytest.raises(ImproperlyConfigured):
        validate_key_separation()
