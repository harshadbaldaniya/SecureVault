"""Heuristic password-strength / entropy estimate.

This is an *estimate*, not a guarantee. It starts from the size of the character pool
(length x log2(pool)) and then removes credit for patterns that make guessing easier:
repeated characters, ascending/descending runs, and common passwords or words. It cannot
know about leaked passwords, personal information or clever substitutions, so it can
overestimate. Use it to nudge users, never as proof that a secret is safe.

The same algorithm is mirrored in the frontend for live feedback (tests share vectors).
"""

import math

COMMON_PASSWORDS = frozenset(
    {
        "password", "passw0rd", "123456", "1234567", "12345678", "123456789", "1234567890", "qwerty", "qwertyuiop",
        "letmein", "welcome", "admin", "administrator", "iloveyou", "monkey", "dragon", "abc123", "password1",
        "111111", "sunshine", "princess", "football", "login", "secret", "master", "changeme", "default",
    }
)
_COMMON_WORD_MIN_LENGTH = 5
_SYMBOL_POOL = 33  # printable ASCII punctuation + space
_OTHER_POOL = 64  # non-ASCII characters (conservative)

LABELS = (
    (28, "very_weak"),
    (36, "weak"),
    (60, "fair"),
    (80, "strong"),
)


def _pool_size(password: str) -> int:
    pool = 0
    if any(c.islower() and c.isascii() for c in password):
        pool += 26
    if any(c.isupper() and c.isascii() for c in password):
        pool += 26
    if any(c.isdigit() and c.isascii() for c in password):
        pool += 10
    if any(c.isascii() and not c.isalnum() for c in password):
        pool += _SYMBOL_POOL
    if any(not c.isascii() for c in password):
        pool += _OTHER_POOL
    return pool


def estimate_entropy_bits(password: str) -> float:
    if not password:
        return 0.0
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        return 4.0

    pool = _pool_size(password)
    effective = 0.0
    previous = None
    step = 0  # direction of the current sequential run (+1 / -1), 0 when none
    for char in password:
        if previous is None:
            effective += 1
        elif char == previous:
            pass  # a repeated character adds nothing new
        else:
            delta = ord(char) - ord(previous)
            if delta in (1, -1) and (step in (0, delta)):
                step = delta  # continuing an ascending/descending run adds nothing new
            else:
                step = 0
                effective += 1
        previous = char

    # Containing a well-known word costs the attacker about one guess, not one per character.
    for word in COMMON_PASSWORDS:
        if len(word) >= _COMMON_WORD_MIN_LENGTH and word in lowered and word != lowered:
            effective -= len(word) - 1
            break

    effective = max(effective, 1.0)
    return round(effective * math.log2(max(pool, 2)), 1)


def strength_label(bits: float) -> str:
    for ceiling, label in LABELS:
        if bits < ceiling:
            return label
    return "very_strong"
