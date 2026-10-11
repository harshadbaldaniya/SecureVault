"""Key-management interface for the vault.

`KeyProvider` is the only place that touches key-encryption keys (KEKs) and the blind-index
key. Vault code asks it to wrap/unwrap per-organization data keys (DEKs) and to compute
blind indexes; it never sees or stores a KEK.

`EnvKeyProvider` reads versioned keyrings from environment variables - fine for development
and small deployments, but anyone who can read the process environment can read the keys.
Production should supply a KMS-backed provider (AWS KMS, GCP KMS, HashiCorp Vault ...) by
setting SV_VAULT_KEY_PROVIDER to its dotted path. No KMS provider is implemented yet.

Key separation (enforced at startup by `validate_key_separation`):
  KEKs, the blind-index key and the MFA key must all be different key material.
"""

import hashlib
import hmac
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from core.crypto import Keyring, decrypt_token, encrypt_to_token, mfa_keyring

BLIND_INDEX_DOMAIN = b"securevault:blind-index:v1|"


class KeyProvider(ABC):
    @abstractmethod
    def wrap(self, key: bytes, aad: bytes) -> str:
        """Encrypt a data key under the current KEK. Returns a token that embeds the KEK version."""

    @abstractmethod
    def unwrap(self, token: str, aad: bytes) -> bytes:
        """Decrypt a wrapped data key (any known KEK version)."""

    @abstractmethod
    def current_kek_version(self) -> int: ...

    @abstractmethod
    def blind_index(self, data: bytes, *, version: int | None = None) -> tuple[int, str]:
        """HMAC-SHA-256 of `data` under the blind-index key. Returns (key version, hex digest)."""

    @abstractmethod
    def current_blind_index_version(self) -> int: ...


class EnvKeyProvider(KeyProvider):
    def __init__(self) -> None:
        self._kek = Keyring.parse(settings.VAULT_KEK_KEYS, "SV_VAULT_KEK_KEYS")
        self._blind = Keyring.parse(settings.VAULT_BLIND_INDEX_KEYS, "SV_BLIND_INDEX_KEYS")

    def wrap(self, key: bytes, aad: bytes) -> str:
        return encrypt_to_token(self._kek, key, aad)

    def unwrap(self, token: str, aad: bytes) -> bytes:
        return decrypt_token(self._kek, token, aad)

    def current_kek_version(self) -> int:
        return self._kek.current_version

    def blind_index(self, data: bytes, *, version: int | None = None) -> tuple[int, str]:
        version = version or self._blind.current_version
        digest = hmac.new(self._blind.key(version), BLIND_INDEX_DOMAIN + data, hashlib.sha256).hexdigest()
        return version, digest

    def current_blind_index_version(self) -> int:
        return self._blind.current_version


def get_key_provider() -> KeyProvider:
    return import_string(settings.VAULT_KEY_PROVIDER)()


def validate_key_separation() -> None:
    """Fail fast at startup if key purposes share material or a keyring is missing/malformed."""
    kek = Keyring.parse(settings.VAULT_KEK_KEYS, "SV_VAULT_KEK_KEYS")
    blind = Keyring.parse(settings.VAULT_BLIND_INDEX_KEYS, "SV_BLIND_INDEX_KEYS")
    mfa = mfa_keyring()
    rings = {
        "vault KEK": set(kek.keys.values()),
        "blind index": set(blind.keys.values()),
        "MFA": set(mfa.keys.values()),
    }
    names = list(rings)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            if rings[first] & rings[second]:
                raise ImproperlyConfigured(f"The {first} and {second} keyrings must not share key material.")
