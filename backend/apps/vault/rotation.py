"""Key rotation procedures. Run by operators via `manage.py rotate_vault_keys`.

Three independent procedures, each safe to re-run:

1. rewrap_data_keys()    - after adding a new KEK version: re-wrap every organization DEK under it.
                           Cheap; no secret is re-encrypted.
2. rotate_data_key(org)  - replace an organization's DEK: create version N+1 and re-encrypt every
                           credential and note under it. Old versions stay RETIRED (readable) so an
                           interrupted run, or a restore from an older backup, still works.
3. reindex_blind_indexes() - after adding a new blind-index key version: recompute every credential's
                           index (requires decrypting each password once).

Rotation only ever re-encrypts data the server could already decrypt; it does not widen anyone's access.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.organizations.models import Organization

from . import encryption
from .keys import get_key_provider
from .models import Credential, OrganizationKey, SecureNote
from .services import FIELD_CONTENT, FIELD_PASSWORD, KIND_CREDENTIAL, KIND_NOTE

logger = logging.getLogger(__name__)


def rewrap_data_keys() -> int:
    provider = get_key_provider()
    current = provider.current_kek_version()
    rewrapped = 0
    for row in OrganizationKey.objects.exclude(kek_version=current).select_related("organization"):
        with transaction.atomic():
            locked = OrganizationKey.objects.select_for_update().get(pk=row.pk)
            if locked.kek_version == current:
                continue
            aad = encryption._dek_aad(locked.organization_id, locked.version)
            dek = provider.unwrap(locked.wrapped_key, aad)
            locked.wrapped_key = provider.wrap(dek, aad)
            locked.kek_version = encryption._kek_version_of(locked.wrapped_key)
            locked.save(update_fields=["wrapped_key", "kek_version", "updated_at"])
            audit.record(
                AuditAction.KEY_ROTATION, organization=locked.organization, target_type="organization_key",
                target_id=str(locked.pk), metadata={"operation": "rewrap", "kek_version": locked.kek_version},
            )
            rewrapped += 1
    return rewrapped


def _items(organization):
    yield Credential, KIND_CREDENTIAL, FIELD_PASSWORD
    yield SecureNote, KIND_NOTE, FIELD_CONTENT


def rotate_data_key(organization: Organization) -> int:
    """Create a new DEK version for `organization` and re-encrypt everything under it. Returns records moved."""
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization.pk)
        old = encryption.active_key(organization)
        old.status = OrganizationKey.Status.RETIRED
        old.retired_at = timezone.now()
        old.save(update_fields=["status", "retired_at", "updated_at"])
        new, _ = encryption._new_key_row(organization, old.version + 1, OrganizationKey.Status.ACTIVE)
        audit.record(
            AuditAction.KEY_ROTATION, organization=organization, target_type="organization_key", target_id=str(new.pk),
            metadata={"operation": "rotate_data_key", "from_version": old.version, "to_version": new.version},
        )

    moved = 0
    for model, kind, field in _items(organization):
        outdated = model.objects.filter(organization=organization).exclude(key_version=new.version)
        for pk in list(outdated.values_list("pk", flat=True)):
            with transaction.atomic():
                item = model.objects.select_for_update().get(pk=pk)
                if item.key_version == new.version:
                    continue
                plaintext = encryption.open_sealed(
                    item.organization_id, kind, item.pk, field, item.secret_ciphertext, item.key_version
                )
                item.secret_ciphertext, item.key_version = encryption.seal(
                    organization, kind, item.pk, field, plaintext
                )
                item.save(update_fields=["secret_ciphertext", "key_version", "updated_at"])
                del plaintext
                moved += 1
    return moved


def reindex_blind_indexes() -> int:
    provider = get_key_provider()
    current = provider.current_blind_index_version()
    reindexed = 0
    stale = Credential.objects.exclude(blind_index_version=current).values_list("pk", flat=True)
    for pk in list(stale):
        with transaction.atomic():
            item = Credential.objects.select_for_update().get(pk=pk)
            if item.blind_index_version == current:
                continue
            plaintext = encryption.open_sealed(
                item.organization_id, KIND_CREDENTIAL, item.pk, FIELD_PASSWORD, item.secret_ciphertext, item.key_version
            )
            item.blind_index_version, item.blind_index = provider.blind_index(
                f"{item.organization_id}|{plaintext}".encode()
            )
            item.save(update_fields=["blind_index", "blind_index_version", "updated_at"])
            del plaintext
            reindexed += 1
    return reindexed
