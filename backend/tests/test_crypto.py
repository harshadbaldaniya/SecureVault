import base64
import os

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.crypto import DecryptionError, Keyring, b64d, decrypt_token, encrypt_to_token


def make_key(version: int) -> str:
    return f"{version}:" + base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_round_trip_with_associated_data():
    ring = Keyring.parse(make_key(1), "TEST")
    token = encrypt_to_token(ring, b"top secret", b"ctx")
    assert b"top secret" not in token.encode()
    assert decrypt_token(ring, token, b"ctx") == b"top secret"


def test_every_encryption_uses_a_fresh_12_byte_nonce():
    ring = Keyring.parse(make_key(1), "TEST")
    tokens = [encrypt_to_token(ring, b"same", b"ctx") for _ in range(50)]
    nonces = [b64d(t.split(":")[1]) for t in tokens]
    assert all(len(n) == 12 for n in nonces)
    assert len(set(nonces)) == 50
    assert len(set(tokens)) == 50


def test_wrong_associated_data_is_rejected():
    ring = Keyring.parse(make_key(1), "TEST")
    token = encrypt_to_token(ring, b"secret", b"user-A")
    with pytest.raises(DecryptionError):
        decrypt_token(ring, token, b"user-B")


def test_tampered_ciphertext_is_rejected():
    ring = Keyring.parse(make_key(1), "TEST")
    version, nonce, ciphertext = encrypt_to_token(ring, b"secret", b"ctx").split(":")
    flipped = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    with pytest.raises(DecryptionError):
        decrypt_token(ring, f"{version}:{nonce}:{flipped}", b"ctx")


def test_wrong_key_is_rejected():
    token = encrypt_to_token(Keyring.parse(make_key(1), "TEST"), b"secret", b"ctx")
    with pytest.raises(DecryptionError):
        decrypt_token(Keyring.parse(make_key(1), "TEST"), token, b"ctx")


def test_rotation_new_version_encrypts_old_version_still_decrypts():
    old_key = make_key(1)
    old_token = encrypt_to_token(Keyring.parse(old_key, "TEST"), b"legacy", b"ctx")
    rotated = Keyring.parse(f"{old_key},{make_key(2)}", "TEST")
    assert encrypt_to_token(rotated, b"new", b"ctx").startswith("v2:")
    assert decrypt_token(rotated, old_token, b"ctx") == b"legacy"


@pytest.mark.parametrize(
    "raw", ["", "1:short", "x:" + "A" * 43, "0:" + base64.urlsafe_b64encode(os.urandom(32)).decode()]
)
def test_bad_keyring_configuration_fails_loudly(raw):
    with pytest.raises(ImproperlyConfigured):
        Keyring.parse(raw, "TEST")


@pytest.mark.parametrize("token", ["garbage", "v1:abc", "1:aaa:bbb", "v1:AAAA:BBBB"])
def test_malformed_tokens_raise_decryption_error(token):
    with pytest.raises(DecryptionError):
        decrypt_token(Keyring.parse(make_key(1), "TEST"), token, b"ctx")
