import secrets
import string

import pytest

from apps.vault.strength import estimate_entropy_bits, strength_label


def test_empty_password_has_no_entropy():
    assert estimate_entropy_bits("") == 0.0


@pytest.mark.parametrize("password", ["password", "PASSWORD", "123456", "Qwerty", "letmein", "changeme"])
def test_common_passwords_score_almost_nothing(password):
    assert estimate_entropy_bits(password) <= 4.0
    assert strength_label(estimate_entropy_bits(password)) == "very_weak"


def test_repeats_and_sequences_earn_no_credit():
    assert estimate_entropy_bits("aaaaaaaaaaaaaaaa") < estimate_entropy_bits("a1b2c3d4e5f6g7h8")
    assert estimate_entropy_bits("abcdefghijklmnop") < 30  # one ascending run
    assert estimate_entropy_bits("9876543210") < 20
    assert estimate_entropy_bits("abcdefgh") == estimate_entropy_bits("abcdefgh"[0] + "")  # whole run ~ one char


def test_containing_a_common_word_is_penalised():
    assert estimate_entropy_bits("Xk9password") < estimate_entropy_bits("Xk9plaintext")


@pytest.mark.parametrize(
    "password,bits,label",
    [
        ("abc", 1.0 * 4.7, "very_weak"),  # a run counts as one character: 4.7 bits
        ("hunter", 28.2, "weak"),  # 6 lowercase letters: 6 x log2(26)
        ("Tangerine42", 65.5, "strong"),  # 11 chars over a 62-symbol pool
        ("Tr0ub4dor&3-x", 85.4, "very_strong"),  # 13 x log2(95): lower+upper+digits+symbols
        ("Xq7!Plaintext-Marker-9137", 164.2, "very_strong"),  # 25 x log2(95)
    ],
)
def test_labels_follow_the_documented_thresholds(password, bits, label):
    assert estimate_entropy_bits(password) == pytest.approx(bits, abs=0.2)
    assert strength_label(estimate_entropy_bits(password)) == label


@pytest.mark.parametrize(
    "bits,label",
    [
        (0, "very_weak"), (27.9, "very_weak"), (28, "weak"), (35.9, "weak"), (36, "fair"),
        (59.9, "fair"), (60, "strong"), (79.9, "strong"), (80, "very_strong"),
    ],
)
def test_label_boundaries(bits, label):
    assert strength_label(bits) == label


def test_known_limitation_ordinary_dictionary_words_are_overestimated():
    """The estimator knows only a tiny list of notorious passwords, not a dictionary or leaked-password corpus.
    A single English word therefore scores as if random. This is why the score is advice, not proof,
    and why the UI says 'estimate'. Do not use it as a security gate."""
    assert estimate_entropy_bits("tangerine") > 36


def test_longer_and_more_varied_passwords_score_higher():
    base = "Xk9mQ2vL"
    assert estimate_entropy_bits(base + "7pRw") > estimate_entropy_bits(base)
    assert estimate_entropy_bits("xkqmvlpr") < estimate_entropy_bits("xKqMvLpR") < estimate_entropy_bits("xK9M!LpR")


def test_random_passwords_are_scored_high():
    alphabet = string.ascii_letters + string.digits + string.punctuation
    for _ in range(25):
        password = "".join(secrets.choice(alphabet) for _ in range(20))
        assert estimate_entropy_bits(password) >= 80 or any(c * 2 in password for c in password)


def test_unicode_characters_widen_the_pool_without_crashing():
    assert estimate_entropy_bits("пароль-Ключ-密码-9") > estimate_entropy_bits("parol-Kluch-pw-9") - 20
    assert estimate_entropy_bits("🙂🙂🔑🔑🔒🔒") > 0


def test_the_estimate_is_deterministic():
    assert estimate_entropy_bits("Xq7!Plaintext-Marker-9137") == estimate_entropy_bits("Xq7!Plaintext-Marker-9137")


def test_the_estimate_does_not_depend_on_python_hash_randomisation():
    """Regression: choosing 'the first common word found' by iterating a set varied between interpreter runs."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import os,sys; sys.path.insert(0,'.'); os.environ['DJANGO_SETTINGS_MODULE']='config.settings';"
        "from apps.vault.strength import estimate_entropy_bits as e;"
        "print(e('passwordqwerty'), e('qwertypassword12'), e('welcomeadmin!'))"
    )
    backend_dir = Path(__file__).resolve().parents[1]
    results = set()
    for seed in ("1", "2", "3", "99"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-I", "-c", code], cwd=backend_dir, env=env, capture_output=True, text=True, check=True
        )
        results.add(out.stdout.strip())
    assert len(results) == 1


VECTORS_FILE = __import__("pathlib").Path(__file__).resolve().parents[2] / "shared" / "strength-vectors.json"


@pytest.mark.skipif(not VECTORS_FILE.exists(), reason="shared vectors not present (e.g. backend-only container)")
def test_estimator_matches_the_shared_vectors_used_by_the_frontend():
    import json

    vectors = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))
    assert len(vectors) >= 30
    for vector in vectors:
        bits = estimate_entropy_bits(vector["password"])
        assert bits == vector["bits"], vector["password"]
        assert strength_label(bits) == vector["label"], vector["password"]
