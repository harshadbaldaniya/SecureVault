#!/usr/bin/env bash
# Logical backup of the production database: a compressed pg_dump (custom format) plus a SHA-256 checksum.
#
#   ./infrastructure/scripts/backup.sh [output-dir]        # default: ./backups
#
# WHAT THE DUMP CONTAINS: encrypted credentials and notes, wrapped per-organization data keys, password hashes,
# the audit trail. WHAT IT DOES NOT CONTAIN: the key-encryption keys (SV_VAULT_KEK_KEYS, SV_MFA_ENCRYPTION_KEYS,
# SV_BLIND_INDEX_KEYS). Back those up separately, offline, with different access controls; without them a restored
# database cannot be decrypted. Encrypt the dump itself before it leaves this machine (for example `age` or `gpg`).
set -euo pipefail

cd "$(dirname "$0")/../.."
compose=(docker compose --env-file "${ENV_FILE:-.env.prod}" -f docker-compose.prod.yml)  # COMPOSE_PROJECT_NAME selects the stack
out_dir="${1:-backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="securevault-${stamp}.dump"

mkdir -p "$out_dir"
# Dump to a file inside the container and copy it out: binary data never passes through a shell pipe (which
# corrupts it on Windows terminals).
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner -f /tmp/backup.dump'
"${compose[@]}" cp db:/tmp/backup.dump "${out_dir}/${name}"
"${compose[@]}" exec -T db rm -f /tmp/backup.dump

(cd "$out_dir" && sha256sum "$name" > "${name}.sha256")
echo "Wrote ${out_dir}/${name} ($(wc -c < "${out_dir}/${name}") bytes) and ${name}.sha256"
echo "Remember: this file is useless without the key material, and it must be stored encrypted."
