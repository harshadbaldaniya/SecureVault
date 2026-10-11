"""Envelope encryption for vault secrets.

  KEK (outside the database, via KeyProvider)
    └─ wraps ─▶ per-organization data key (DEK, stored wrapped in OrganizationKey)
                  └─ AES-256-GCM encrypts ─▶ each secret (fresh random 12-byte nonce every time)

Associated data (AAD) binds every ciphertext to where it belongs:

    securevault:vault:v1|<organization id>|<kind>|<record id>|<field>

so a ciphertext copied into a different record, field or organization fails authentication.
"v1" is the AAD *scheme* version; changing the scheme requires a migration that re-encrypts.

Only `apps.vault.services` (and key rotation) may call `open_sealed`: decryption must always
follow `core.access_gate.authorize`.
"""

import logging
import os

from django.db import transaction

from apps.organizations.models import Organization
from core.crypto import DecryptionError, Keyring, decrypt_token, encrypt_to_token

from .keys import get_key_provider
from .models import OrganizationKey

logger = logging.getLogger(__name__)

AAD_SCHEME = "securevault:vault:v1"
DEK_BYTES = 32


def secret_aad(organization_id, kind: str, record_id, field: str) -> bytes:
    return f"{AAD_SCHEME}|{organization_id}|{kind}|{record_id}|{field}".encode()


def _dek_aad(organization_id, version: int) -> bytes:
    return f"securevault:org-dek:v1|{organization_id}|{version}".encode()


def _kek_version_of(token: str) -> int:
    return int(token.split(":", 1)[0].lstrip("v"))


def _new_key_row(organization, version: int, status: str) -> tuple[OrganizationKey, bytes]:
    provider = get_key_provider()
    dek = os.urandom(DEK_BYTES)
    wrapped = provider.wrap(dek, _dek_aad(organization.pk, version))
    row = OrganizationKey.objects.create(
        organization=organization,
        version=version,
        wrapped_key=wrapped,
        kek_version=_kek_version_of(wrapped),
        status=status,
    )
    return row, dek


def active_key(organization) -> OrganizationKey:
    """The organization's ACTIVE key row, created (race-free) on first use."""
    row = OrganizationKey.objects.filter(organization=organization, status=OrganizationKey.Status.ACTIVE).first()
    if row is not None:
        return row
    with transaction.atomic():
        # Serialise first-use creation per organization.
        Organization.objects.select_for_update().get(pk=organization.pk)
        row = OrganizationKey.objects.filter(organization=organization, status=OrganizationKey.Status.ACTIVE).first()
        if row is None:
            latest = OrganizationKey.objects.filter(organization=organization).order_by("-version").first()
            row, _ = _new_key_row(organization, (latest.version + 1) if latest else 1, OrganizationKey.Status.ACTIVE)
        return row


def _unwrap(row: OrganizationKey) -> bytes:
    return get_key_provider().unwrap(row.wrapped_key, _dek_aad(row.organization_id, row.version))


def key_row(organization_id, version: int) -> OrganizationKey:
    try:
        return OrganizationKey.objects.get(organization_id=organization_id, version=version)
    except OrganizationKey.DoesNotExist:
        raise DecryptionError(f"No data key version {version} for this organization") from None


def seal(organization, kind: str, record_id, field: str, plaintext: str) -> tuple[str, int]:
    """Encrypt `plaintext` under the organization's active DEK. Returns (token, DEK version)."""
    row = active_key(organization)
    ring = Keyring({row.version: _unwrap(row)})
    token = encrypt_to_token(ring, plaintext.encode("utf-8"), secret_aad(organization.pk, kind, record_id, field))
    return token, row.version


def open_sealed(organization_id, kind: str, record_id, field: str, token: str, key_version: int) -> str:
    """Decrypt a token. Raises DecryptionError if it was tampered with, moved, or the key is wrong."""
    row = key_row(organization_id, key_version)
    ring = Keyring({row.version: _unwrap(row)})
    plaintext = decrypt_token(ring, token, secret_aad(organization_id, kind, record_id, field))
    return plaintext.decode("utf-8")
