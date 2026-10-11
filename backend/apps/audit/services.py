"""Writing and verifying audit records.

Failure policy:
* `record()` raises if the audit write fails. Callers invoke it inside the same
  transaction as the action, so an action that cannot be audited does not happen
  (fail closed).
* `record(..., fail_silently=True)` is only for events about requests that are
  being refused anyway (e.g. failed sign-in): losing that row must not turn a
  denial into an error page, and it can never grant access.
"""

import hashlib
import json
import logging
import re

from django.db import transaction
from django.utils import timezone

from core import request_context

from .models import AuditAction, AuditChainHead, AuditLog, AuditOutcome

logger = logging.getLogger(__name__)

GLOBAL_CHAIN = "global"
GENESIS_HASH = "0" * 64
REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"pass(word|phrase)?|secret|token|api[_-]?key|private|otp|totp|ciphertext|plaintext|session|csrf|cookie|"
    r"authorization|credential_value|\bkey\b",
    re.IGNORECASE,
)
# Settings *about* secrets (e.g. min_password_length) are not secrets themselves.
_NON_SECRET_KEY = re.compile(r"_(length|age_days|count|required)$", re.IGNORECASE)
_MAX_METADATA_BYTES = 8_000


def chain_key_for(organization) -> str:
    return f"org:{organization.pk}" if organization is not None else GLOBAL_CHAIN


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key)) and not _NON_SECRET_KEY.search(key)


def sanitize(value, depth: int = 0):
    """Recursively redact values under secret-looking keys and force JSON-safe types."""
    if depth > 5:
        return REDACTED
    if isinstance(value, dict):
        return {str(k): (REDACTED if _is_sensitive_key(str(k)) else sanitize(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [sanitize(v, depth + 1) for v in value]
    if value is None or isinstance(value, bool | int | str):
        return value
    return str(value)


def compute_hash(entry: AuditLog) -> str:
    payload = {
        "chain": entry.chain_key,
        "seq": entry.sequence,
        "prev": entry.prev_hash,
        "at": entry.created_at.isoformat(),
        "org": str(entry.organization_id) if entry.organization_id else None,
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "actor_email": entry.actor_email,
        "action": entry.action,
        "outcome": entry.outcome,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "target_label": entry.target_label,
        "reason": entry.reason,
        "metadata": entry.metadata,
        "ip": entry.ip_address,
        "ua": entry.user_agent,
        "request_id": entry.request_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record(
    action: str,
    *,
    actor=None,
    organization=None,
    outcome: str = AuditOutcome.SUCCESS,
    target=None,
    target_type: str = "",
    target_id: str = "",
    target_label: str = "",
    reason: str = "",
    metadata: dict | None = None,
    fail_silently: bool = False,
) -> AuditLog | None:
    if action not in AuditAction.values:
        raise ValueError(f"Unknown audit action {action!r}")
    try:
        return _append(
            action=action,
            actor=actor,
            organization=organization,
            outcome=outcome,
            target=target,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            reason=reason,
            metadata=metadata,
        )
    except Exception:
        if not fail_silently:
            raise
        logger.exception("Audit write failed for action %s (fail_silently)", action)
        return None


def _append(*, action, actor, organization, outcome, target, target_type, target_id, target_label, reason, metadata):
    ctx = request_context.current()
    if actor is None and ctx is not None:
        actor = ctx.user
    if organization is None and actor is not None:
        organization = actor.organization
    if target is not None:
        target_type = target_type or target._meta.model_name
        target_id = target_id or str(target.pk)
        target_label = target_label or str(target)

    clean_metadata = json.loads(json.dumps(sanitize(metadata or {})))
    if len(json.dumps(clean_metadata)) > _MAX_METADATA_BYTES:
        clean_metadata = {"truncated": True}
    # Device context, when this request's device was already identified (e.g. by the device-trust check).
    device = getattr(ctx.request, "_sv_device", None) if ctx is not None else None
    if device is not None and "device" not in clean_metadata:
        clean_metadata["device"] = {"id": str(device.pk), "trust": device.trust_state}

    key = chain_key_for(organization)
    with transaction.atomic():
        AuditChainHead.objects.get_or_create(chain_key=key)
        head = AuditChainHead.objects.select_for_update().get(chain_key=key)
        entry = AuditLog(
            chain_key=key,
            sequence=head.last_sequence + 1,
            prev_hash=head.last_hash,
            created_at=timezone.now(),
            organization=organization,
            actor_id=getattr(actor, "pk", None),
            actor_email=getattr(actor, "email", "") or "",
            action=action,
            outcome=outcome,
            target_type=target_type[:40],
            target_id=str(target_id)[:64],
            target_label=str(target_label)[:254],
            reason=reason[:500],
            metadata=clean_metadata,
            ip_address=ctx.ip_address if ctx else None,
            user_agent=ctx.user_agent if ctx else "",
            request_id=ctx.request_id if ctx else "",
        )
        entry.hash = compute_hash(entry)
        entry.save()
        head.last_sequence = entry.sequence
        head.last_hash = entry.hash
        head.save(update_fields=["last_sequence", "last_hash"])
    return entry


def verify_chain(chain_key: str) -> dict:
    """Recompute every hash in a chain. Reports the first broken sequence, if any."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    rows = AuditLog.objects.filter(chain_key=chain_key).order_by("sequence").iterator(chunk_size=2000)
    for entry in rows:
        if entry.sequence != expected_seq or entry.prev_hash != expected_prev or compute_hash(entry) != entry.hash:
            return {"chain": chain_key, "valid": False, "checked": checked, "broken_at_sequence": expected_seq}
        expected_prev = entry.hash
        expected_seq += 1
        checked += 1

    head = AuditChainHead.objects.filter(chain_key=chain_key).first()
    if head is not None and (head.last_sequence != checked or head.last_hash != expected_prev):
        # Rows missing from the end of the chain.
        return {"chain": chain_key, "valid": False, "checked": checked, "broken_at_sequence": checked + 1}
    return {"chain": chain_key, "valid": True, "checked": checked, "broken_at_sequence": None}
