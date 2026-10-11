"""Creates .env for local development from .env.example, replacing every "change-me" with fresh random values.

    py infrastructure/scripts/init_env.py            # Windows
    python3 infrastructure/scripts/init_env.py       # macOS / Linux

It refuses to overwrite an existing .env and never prints the secrets it generates. For production use
.env.prod.example instead (docs/deployment-guide.md); this script is for development only.
"""

import base64
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
target = root / ".env"
if target.exists():
    sys.exit(f"{target} already exists; not overwriting it. Delete it first if you really want fresh secrets.")


def key() -> str:
    return "1:" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


generators = {
    "DJANGO_SECRET_KEY": lambda: secrets.token_urlsafe(64),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "SV_MFA_ENCRYPTION_KEYS": key,
    "SV_VAULT_KEK_KEYS": key,
    "SV_BLIND_INDEX_KEYS": key,
}

lines = []
for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
    name, _, value = line.partition("=")
    if name in generators and value == "change-me":
        line = f"{name}={generators[name]()}"
    lines.append(line)

remaining = [line for line in lines if line.endswith("=change-me")]
if remaining:
    sys.exit(f"Unreplaced placeholders: {remaining}")

# open(..., "x") fails if the file appeared in the meantime; mode 600 where the OS supports it.
with open(target, "x", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(lines) + "\n")
try:
    target.chmod(0o600)
except OSError:
    pass
print(f"Wrote {target} with new random secrets (not shown). Keep this file private; it is git-ignored.")
