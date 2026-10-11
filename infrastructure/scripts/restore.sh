#!/usr/bin/env bash
# Restores a backup into a NEW database next to the live one and verifies it. It never touches the live database.
#
#   ./infrastructure/scripts/restore.sh backups/securevault-20261011T120000Z.dump [target-database]
#
# Default target: securevault_restore. The script then:
#   1. checks the file against its .sha256,
#   2. creates the target database (owned by the owner role) and loads the dump,
#   3. re-applies the application role's privileges,
#   4. verifies the audit hash chain with the application's own tooling (this also proves the keys and code can read
#      the restored data).
# Cutting over to the restored database is a deliberate, manual step; docs/deployment-guide.md lists it.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <backup.dump> [target-database]" >&2
  exit 2
fi
dump="$1"
target="${2:-securevault_restore}"

cd "$(dirname "$0")/../.."
compose=(docker compose --env-file "${ENV_FILE:-.env.prod}" -f docker-compose.prod.yml)  # COMPOSE_PROJECT_NAME selects the stack

if [ -f "${dump}.sha256" ]; then
  (cd "$(dirname "$dump")" && sha256sum --check "$(basename "$dump").sha256")
else
  echo "warning: no ${dump}.sha256 next to the dump; skipping the integrity check" >&2
fi

case "$target" in
  *[!a-zA-Z0-9_]*) echo "target database name may contain letters, digits and underscores only" >&2; exit 2 ;;
esac

"${compose[@]}" cp "$dump" db:/tmp/restore.dump
trap '"${compose[@]}" exec -T db rm -f /tmp/restore.dump' EXIT

"${compose[@]}" exec -T -e TARGET="$target" db sh -c '
  set -e
  if psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '"'"'$TARGET'"'"'" | grep -q 1; then
    echo "database $TARGET already exists; choose another name or drop it first" >&2; exit 3
  fi
  createdb -U "$POSTGRES_USER" -O "$SV_OWNER_DB_USER" "$TARGET"
  pg_restore -U "$POSTGRES_USER" -d "$TARGET" --no-owner --role="$SV_OWNER_DB_USER" --exit-on-error /tmp/restore.dump
'

# Grants and verification run through the migrate service definition (owner credentials, same keys as production).
"${compose[@]}" run --rm -T -e POSTGRES_DB="$target" migrate sh -c '
  python manage.py apply_db_grants --role "$SV_APP_DB_USER" >/dev/null &&
  python manage.py verify_audit_chain
'
echo "Restored into database '$target' and the audit chain verified."
