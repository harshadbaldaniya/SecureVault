"""Regenerates shared/strength-vectors.json from the backend estimator (the reference implementation).

Run only when the algorithm intentionally changes:  python tests/make_strength_vectors.py
Both the backend and the frontend tests then check their implementations against the file.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.vault.strength import estimate_entropy_bits, strength_label  # noqa: E402

PASSWORDS = [
    "", "a", "abc", "password", "PASSWORD", "123456", "qwerty", "letmein", "hunter", "tangerine", "Tangerine42",
    "Tr0ub4dor&3-x", "Xq7!Plaintext-Marker-9137", "aaaaaaaaaaaaaaaa", "abcdefghijklmnop", "9876543210",
    "a1b2c3d4e5f6g7h8", "Xk9password", "Xk9plaintext", "passwordqwerty", "qwertypassword12", "welcomeadmin!",
    "xkqmvlpr", "xKqMvLpR", "xK9M!LpR", "correct horse battery staple", "пароль-Ключ-密码-9", "🙂🙂🔑🔑🔒🔒",
    "ABCDEFGH", "zyxwvuts", "abab abab", "!!!!!!!!", "P@ssw0rd!2026", "Aa1!Aa1!Aa1!Aa1!", "          ",
    "tab\tinside", "mixedCASEnoDigits", "ALLUPPER123456", "lower&symbols&only", "1234567890abcdefghij",
]

vectors = [{"password": p, "bits": estimate_entropy_bits(p), "label": strength_label(estimate_entropy_bits(p))} for p in PASSWORDS]
target = Path(__file__).resolve().parents[2] / "shared" / "strength-vectors.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(vectors, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"wrote {len(vectors)} vectors to {target}")
