"""TOTP multi-factor authentication (RFC 6238) and recovery codes."""

import hashlib
import hmac
import secrets
import time

import pyotp
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.policies.models import policy_for
from core.crypto import decrypt_token, encrypt_to_token, mfa_keyring
from core.exceptions import ServiceError

from .models import RecoveryCode, TOTPDevice, User
from .services import revoke_sessions

ISSUER = "SecureVault"
STEP_SECONDS = 30
ALLOWED_DRIFT_STEPS = 1  # accept the previous/next 30 s window for clock skew
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # 31 symbols; no 0/o/1/l/i look-alikes
_RECOVERY_LENGTH = 16  # 16 * log2(31) ≈ 79 bits of entropy


def _aad(user_id) -> bytes:
    return f"securevault:totp-secret:v1:{user_id}".encode()


def _decrypt_secret(device: TOTPDevice) -> str:
    return decrypt_token(mfa_keyring(), device.secret_encrypted, _aad(device.user_id)).decode()


def _matching_step(secret: str, code: str) -> int | None:
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret, interval=STEP_SECONDS)
    current = int(time.time() // STEP_SECONDS)
    for step in range(current - ALLOWED_DRIFT_STEPS, current + ALLOWED_DRIFT_STEPS + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def _normalise_recovery_code(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(_normalise_recovery_code(code).encode()).hexdigest()


def _replace_recovery_codes(user: User) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        codes.append("-".join(raw[i : i + 4] for i in range(0, _RECOVERY_LENGTH, 4)))
    RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=_hash_recovery_code(c)) for c in codes])
    return codes


def has_confirmed_totp(user: User) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


def enrollment_required(user: User) -> bool:
    return policy_for(user.organization).require_mfa and not has_confirmed_totp(user)


@transaction.atomic
def begin_totp_setup(user: User) -> tuple[str, str]:
    """Create (or replace) an unconfirmed device. Returns (secret, otpauth URI) for the QR code."""
    existing = TOTPDevice.objects.select_for_update().filter(user=user).first()
    if existing is not None and existing.confirmed_at is not None:
        raise ServiceError("MFA is already enabled. Disable it first to enrol a new device.", "mfa_already_enabled")
    secret = pyotp.random_base32()  # 160-bit secret
    encrypted = encrypt_to_token(mfa_keyring(), secret.encode(), _aad(user.pk))
    TOTPDevice.objects.update_or_create(
        user=user, defaults={"secret_encrypted": encrypted, "confirmed_at": None, "last_used_step": 0}
    )
    uri = pyotp.TOTP(secret, interval=STEP_SECONDS).provisioning_uri(name=user.email, issuer_name=ISSUER)
    return secret, uri


@transaction.atomic
def confirm_totp(user: User, code: str) -> list[str]:
    device = TOTPDevice.objects.select_for_update().filter(user=user).first()
    if device is None:
        raise ServiceError("Start MFA setup first.", "mfa_not_started")
    if device.confirmed_at is not None:
        raise ServiceError("MFA is already enabled.", "mfa_already_enabled")
    step = _matching_step(_decrypt_secret(device), code)
    if step is None:
        raise ServiceError("Invalid verification code.", "invalid_mfa_code")
    device.confirmed_at = timezone.now()
    device.last_used_step = step
    device.save(update_fields=["confirmed_at", "last_used_step"])
    codes = _replace_recovery_codes(user)
    audit.record(AuditAction.MFA_ENROLL, actor=user, target=user, target_type="user")
    return codes


@transaction.atomic
def verify_second_factor(user: User, code: str) -> str | None:
    """Check a TOTP or recovery code. Returns the method used, or None. Consumes what it accepts."""
    device = TOTPDevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
    if device is None:
        return None
    step = _matching_step(_decrypt_secret(device), code)
    if step is not None:
        if step <= device.last_used_step:
            return None  # replay of an already-used code
        device.last_used_step = step
        device.save(update_fields=["last_used_step"])
        return "totp"
    recovery = (
        RecoveryCode.objects.select_for_update()
        .filter(user=user, code_hash=_hash_recovery_code(code), used_at__isnull=True)
        .first()
    )
    if recovery is not None:
        recovery.used_at = timezone.now()
        recovery.save(update_fields=["used_at"])
        return "recovery_code"
    return None


def _reauthenticate(user: User, password: str, code: str) -> None:
    if not user.check_password(password) or verify_second_factor(user, code) is None:
        raise ServiceError("Password or verification code is incorrect.", "reauth_failed")


@transaction.atomic
def disable_totp(user: User, password: str, code: str) -> None:
    if policy_for(user.organization).require_mfa:
        raise ServiceError("Your organization requires MFA; it cannot be disabled.", "mfa_required_by_policy")
    _reauthenticate(user, password, code)
    TOTPDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
    audit.record(AuditAction.MFA_DISABLE, actor=user, target=user, target_type="user")


@transaction.atomic
def regenerate_recovery_codes(user: User, password: str, code: str) -> list[str]:
    _reauthenticate(user, password, code)
    codes = _replace_recovery_codes(user)
    audit.record(AuditAction.MFA_ENROLL, actor=user, target=user, target_type="user",
                 metadata={"recovery_codes_regenerated": True})
    return codes


@transaction.atomic
def admin_reset_mfa(*, actor: User, user: User) -> None:
    """Account recovery for a lost authenticator: remove MFA and end the user's sessions."""
    if actor.pk == user.pk:
        raise ServiceError("You cannot reset your own MFA.", "self_change")
    TOTPDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
    killed = revoke_sessions([user])
    audit.record(AuditAction.MFA_RESET, actor=actor, target=user, target_type="user",
                 metadata={"sessions_revoked": killed})
