"""AES-256-GCM authenticated encryption with versioned keyrings.

Uses the vetted `cryptography` library; no custom primitives.
* Every encryption uses a fresh 12-byte nonce from os.urandom (CSPRNG).
* Associated data (AAD) binds a ciphertext to its context (purpose, record ID),
  so a ciphertext copied into another row or field fails to decrypt.
* Keys come from environment configuration, never from the database or frontend.
  Each purpose has its own keyring (MFA secrets now; vault and blind-index keys in Phase 2).
* Keyrings are versioned: the highest version encrypts, every listed version decrypts,
  which allows key rotation without downtime.

Keyring format (env var): "1:<base64url 32 bytes>,2:<base64url 32 bytes>"
Generate a key: py -c "import base64,os; print('1:' + base64.urlsafe_b64encode(os.urandom(32)).decode())"
"""

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

NONCE_BYTES = 12
KEY_BYTES = 32


class DecryptionError(Exception):
    """Ciphertext could not be authenticated (wrong key, wrong AAD, or tampered data)."""


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Keyring:
    keys: dict[int, bytes]

    @property
    def current_version(self) -> int:
        return max(self.keys)

    def key(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except KeyError:
            raise DecryptionError(f"Unknown key version {version}") from None

    @classmethod
    def parse(cls, raw: str, setting_name: str) -> "Keyring":
        keys: dict[int, bytes] = {}
        for item in (raw or "").split(","):
            item = item.strip()
            if not item:
                continue
            version_text, _, encoded = item.partition(":")
            try:
                version = int(version_text)
                key = b64d(encoded)
            except ValueError:
                raise ImproperlyConfigured(f"{setting_name} has a malformed entry.") from None
            if version < 1 or len(key) != KEY_BYTES:
                raise ImproperlyConfigured(f"{setting_name}: each key must be version>=1 and exactly 32 bytes.")
            keys[version] = key
        if not keys:
            raise ImproperlyConfigured(f"{setting_name} is not configured.")
        return cls(keys)


def encrypt_to_token(keyring: Keyring, plaintext: bytes, aad: bytes) -> str:
    """Encrypt and serialise as 'v<version>:<nonce>:<ciphertext+tag>' (base64url)."""
    version = keyring.current_version
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(keyring.key(version)).encrypt(nonce, plaintext, aad)
    return f"v{version}:{b64e(nonce)}:{b64e(ciphertext)}"


def decrypt_token(keyring: Keyring, token: str, aad: bytes) -> bytes:
    try:
        version_part, nonce_part, ciphertext_part = token.split(":")
        if not version_part.startswith("v"):
            raise ValueError
        version = int(version_part[1:])
        nonce, ciphertext = b64d(nonce_part), b64d(ciphertext_part)
    except ValueError:
        raise DecryptionError("Malformed ciphertext token") from None
    if len(nonce) != NONCE_BYTES:
        raise DecryptionError("Malformed nonce")
    try:
        return AESGCM(keyring.key(version)).decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise DecryptionError("Ciphertext failed authentication") from None


def mfa_keyring() -> Keyring:
    return Keyring.parse(settings.MFA_ENCRYPTION_KEYS, "SV_MFA_ENCRYPTION_KEYS")
