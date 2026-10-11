#!/bin/sh
# Creates the two non-superuser roles the application uses. Runs once, when the database volume is first
# initialised (official postgres image behaviour).
#
#   POSTGRES_USER   bootstrap superuser created by the image. Only this container knows its password; use it for
#                   administration (backups, restores), never for the application.
#   SV_OWNER_DB_USER  owns the database and its tables; runs migrations. NOT a superuser. Only the one-shot `migrate`
#                   job receives its password.
#   SV_APP_DB_USER  what the web and worker processes connect as. Gets read/write access to application data, no
#                   schema changes and no UPDATE/DELETE/TRUNCATE on the audit trail (manage.py apply_db_grants, which
#                   runs after migrate because the tables do not exist yet).
#
# Re-running this script is safe. To change a password afterwards, as the superuser:
#   ALTER ROLE <role> PASSWORD '...';
set -eu

: "${SV_OWNER_DB_USER:?SV_OWNER_DB_USER is required}"
: "${SV_OWNER_DB_PASSWORD:?SV_OWNER_DB_PASSWORD is required}"
: "${SV_APP_DB_USER:?SV_APP_DB_USER is required}"
: "${SV_APP_DB_PASSWORD:?SV_APP_DB_PASSWORD is required}"
if [ "$SV_OWNER_DB_USER" = "$SV_APP_DB_USER" ]; then
  echo "SV_OWNER_DB_USER and SV_APP_DB_USER must be different roles" >&2
  exit 1
fi

# psql variables are quoted inside the SQL with format(%I / %L), so no value is ever spliced into SQL text by the
# shell. \gexec runs each generated statement.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_user="$SV_OWNER_DB_USER" -v owner_password="$SV_OWNER_DB_PASSWORD" \
  -v app_user="$SV_APP_DB_USER" -v app_password="$SV_APP_DB_PASSWORD" -v db="$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
              :'owner_user', :'owner_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'owner_user') \gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
              :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

-- The owner role owns the database, and therefore the public schema (owned by pg_database_owner since PostgreSQL 15).
SELECT format('ALTER DATABASE %I OWNER TO %I', :'db', :'owner_user') \gexec

-- Only the superuser, the owner and the application role may connect, and nobody may create objects in public
-- except the owner.
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
