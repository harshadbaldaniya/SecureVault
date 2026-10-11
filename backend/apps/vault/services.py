"""Vault business rules: create / edit / archive / restore / reveal credentials and secure notes.

Order of operations for every sensitive action:
  1. `authorize()` - identity, resource permission, registered zero-trust checks (outside any
     transaction, so a DENIED audit record survives the refusal)
  2. do the work inside one transaction together with its audit record (fail closed)
  3. for reveals: decrypt, write the audit record, and only then return the plaintext

Plaintext secrets are held only in local variables for the duration of the call: never logged,
never placed in audit metadata, never cached.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction, AuditOutcome
from apps.policies.models import SecurityPolicy, policy_for
from core.access_gate import Action, authorize
from core.crypto import DecryptionError
from core.exceptions import ServiceError

from . import encryption
from .keys import get_key_provider
from .models import Credential, SecureNote, VaultItem
from .strength import estimate_entropy_bits

logger = logging.getLogger(__name__)

KIND_CREDENTIAL = "credential"
KIND_NOTE = "note"
FIELD_PASSWORD = "password"  # noqa: S105 - AAD field label, not a secret
FIELD_CONTENT = "content"

_SYMBOLS = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ ")


def kind_of(item: VaultItem) -> str:
    return KIND_CREDENTIAL if isinstance(item, Credential) else KIND_NOTE


def secret_field_of(item: VaultItem) -> str:
    return FIELD_PASSWORD if isinstance(item, Credential) else FIELD_CONTENT


# --------------------------------------------------------------------------- policy


def policy_violations(policy: SecurityPolicy, secret_type: str, secret: str) -> list[str]:
    """Password complexity applies to PASSWORD secrets only (API keys and tokens are machine-generated)."""
    if secret_type != Credential.SecretType.PASSWORD:
        return []
    problems = []
    if len(secret) < policy.min_password_length:
        problems.append(f"Use at least {policy.min_password_length} characters.")
    if policy.require_uppercase and not any(c.isupper() for c in secret):
        problems.append("Include an uppercase letter.")
    if policy.require_numbers and not any(c.isdigit() for c in secret):
        problems.append("Include a number.")
    if policy.require_symbols and not any(c in _SYMBOLS for c in secret):
        problems.append("Include a symbol.")
    return problems


def _check_secret(policy: SecurityPolicy, secret_type: str, secret: str) -> None:
    problems = policy_violations(policy, secret_type, secret)
    if problems:
        raise ServiceError(
            "The password does not meet your organization's policy.", "policy_violation", details={"password": problems}
        )


def _default_expiry(policy: SecurityPolicy, secret_type: str):
    if secret_type == Credential.SecretType.PASSWORD and policy.max_password_age_days:
        return timezone.localdate() + timedelta(days=policy.max_password_age_days)
    return None


def _apply_password(credential: Credential, password: str) -> None:
    ciphertext, version = encryption.seal(
        credential.organization, KIND_CREDENTIAL, credential.pk, FIELD_PASSWORD, password
    )
    provider = get_key_provider()
    credential.secret_ciphertext = ciphertext
    credential.key_version = version
    credential.blind_index_version, credential.blind_index = provider.blind_index(
        f"{credential.organization_id}|{password}".encode()
    )
    credential.entropy_bits = estimate_entropy_bits(password)
    credential.password_changed_at = timezone.now()


# --------------------------------------------------------------------------- credentials


@transaction.atomic
def create_credential(*, user, password: str, **fields) -> Credential:
    policy = policy_for(user.organization)
    secret_type = fields.get("secret_type", Credential.SecretType.PASSWORD)
    _check_secret(policy, secret_type, password)

    credential = Credential(organization=user.organization, owner=user, **fields)
    if credential.expires_at is None:
        credential.expires_at = _default_expiry(policy, secret_type)
    _apply_password(credential, password)
    credential.save()
    audit.record(
        AuditAction.CREATE, actor=user, target=credential, target_type="credential",
        metadata={"secret_type": secret_type, "entropy_bits": credential.entropy_bits},
    )
    return credential


def update_credential(*, user, credential: Credential, password: str | None = None, **fields) -> Credential:
    authorize(user, credential, Action.EDIT)
    with transaction.atomic():
        locked = Credential.objects.select_for_update().select_related("organization").get(pk=credential.pk)
        _ensure_not_archived(locked)
        policy = policy_for(user.organization)
        for name, value in fields.items():
            setattr(locked, name, value)
        changed = sorted(fields)
        if password is not None:
            _check_secret(policy, locked.secret_type, password)
            _apply_password(locked, password)
            changed.append("password")
            if "expires_at" not in fields:  # changing the password renews the policy-driven expiry
                locked.expires_at = _default_expiry(policy, locked.secret_type) or locked.expires_at
        locked.save()
        audit.record(
            AuditAction.EDIT, actor=user, target=locked, target_type="credential", metadata={"changed": changed}
        )
    return locked


# --------------------------------------------------------------------------- secure notes


@transaction.atomic
def create_note(*, user, content: str, **fields) -> SecureNote:
    note = SecureNote(organization=user.organization, owner=user, **fields)
    note.secret_ciphertext, note.key_version = encryption.seal(
        note.organization, KIND_NOTE, note.pk, FIELD_CONTENT, content
    )
    note.save()
    audit.record(AuditAction.CREATE, actor=user, target=note, target_type="note")
    return note


def update_note(*, user, note: SecureNote, content: str | None = None, **fields) -> SecureNote:
    authorize(user, note, Action.EDIT)
    with transaction.atomic():
        locked = SecureNote.objects.select_for_update().select_related("organization").get(pk=note.pk)
        _ensure_not_archived(locked)
        for name, value in fields.items():
            setattr(locked, name, value)
        changed = sorted(fields)
        if content is not None:
            locked.secret_ciphertext, locked.key_version = encryption.seal(
                locked.organization, KIND_NOTE, locked.pk, FIELD_CONTENT, content
            )
            changed.append("content")
        locked.save()
        audit.record(AuditAction.EDIT, actor=user, target=locked, target_type="note", metadata={"changed": changed})
    return locked


# --------------------------------------------------------------------------- archive / restore


def _ensure_not_archived(item: VaultItem) -> None:
    if item.is_archived:
        raise ServiceError("This item is archived. Restore it first.", "archived", status_code=409)


def archive_item(*, user, item: VaultItem) -> VaultItem:
    """DELETE means archive: the encrypted record is kept for the retention period."""
    authorize(user, item, Action.DELETE)
    with transaction.atomic():
        locked = type(item).objects.select_for_update().get(pk=item.pk)
        if locked.is_archived:
            return locked
        locked.archived_at = timezone.now()
        locked.archived_by = user
        locked.save(update_fields=["archived_at", "archived_by", "updated_at"])
        audit.record(
            AuditAction.DELETE, actor=user, target=locked, target_type=kind_of(locked), metadata={"archived": True}
        )
    return locked


def restore_item(*, user, item: VaultItem) -> VaultItem:
    authorize(user, item, Action.EDIT)
    with transaction.atomic():
        locked = type(item).objects.select_for_update().get(pk=item.pk)
        if not locked.is_archived:
            return locked
        locked.archived_at = None
        locked.archived_by = None
        locked.save(update_fields=["archived_at", "archived_by", "updated_at"])
        audit.record(
            AuditAction.EDIT, actor=user, target=locked, target_type=kind_of(locked), metadata={"restored": True}
        )
    return locked


def purge_expired_archives(*, now=None) -> int:
    """Permanently delete items archived longer than the retention period. Returns rows deleted."""
    retention_days = settings.VAULT_ARCHIVE_RETENTION_DAYS
    cutoff = (now or timezone.now()) - timedelta(days=retention_days)
    deleted = 0
    for model in (Credential, SecureNote):
        expired = model.objects.filter(archived_at__isnull=False, archived_at__lt=cutoff)
        for item in expired.select_related("organization"):
            with transaction.atomic():
                audit.record(
                    AuditAction.DELETE,
                    organization=item.organization,
                    target_type=kind_of(item),
                    target_id=str(item.pk),
                    target_label=item.title,
                    metadata={"purged": True, "retention_days": retention_days},
                )
                item.delete()
            deleted += 1
    return deleted


# --------------------------------------------------------------------------- reveal


def reveal(*, user, item: VaultItem, purpose: str) -> str:
    """Decrypt and return an item's secret after the full authorization gate.

    purpose "view" is recorded as REVEAL, "copy" as COPY (the client copies to the clipboard).
    """
    action = Action.COPY if purpose == "copy" else Action.REVEAL
    audit_action = AuditAction.COPY if purpose == "copy" else AuditAction.REVEAL

    authorize(user, item, action)
    _ensure_not_archived(item)

    kind = kind_of(item)
    try:
        secret = encryption.open_sealed(
            item.organization_id, kind, item.pk, secret_field_of(item), item.secret_ciphertext, item.key_version
        )
    except DecryptionError:
        logger.error("Vault decryption failed for %s %s", kind, item.pk)  # ids only, never contents
        audit.record(
            audit_action, actor=user, outcome=AuditOutcome.FAILURE, target=item, target_type=kind,
            reason="decryption_failed", fail_silently=True,
        )
        raise ServiceError(
            "This secret cannot be decrypted. Contact your administrator.", "decryption_failed", status_code=500
        ) from None

    # Audit before the plaintext leaves: if the audit store is down, the reveal is refused.
    audit.record(audit_action, actor=user, target=item, target_type=kind, metadata={"purpose": purpose})
    return secret
