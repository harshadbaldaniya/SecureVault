"""Give the application's PostgreSQL role the privileges it needs, and no more.

Production runs separate database identities (see docker-compose.prod.yml):
- the owner role owns the tables and runs `migrate`. It is not a superuser, and only the short-lived `migrate` job
  holds its password;
- the application role (this command's --role) is what the web and worker processes connect as. It can read and write
  application data, but it cannot change the schema, cannot rewrite migration history, and cannot UPDATE, DELETE or
  TRUNCATE the audit trail.

That last point backs the append-only trigger (apps/audit/migrations/0002): the trigger blocks UPDATE and DELETE for
every role, but a table owner could drop it or TRUNCATE the table. The application role is not the owner, so it
cannot.

Idempotent. Run it as the owner role after every `migrate` (new tables start with no grants for the app role, so a
forgotten run fails closed with "permission denied" rather than open).

    python manage.py apply_db_grants --role securevault_app [--dry-run]
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql

# Tables whose rows the application may add but never alter or remove.
APPEND_ONLY = ("audit_auditlog",)
# The hash-chain head is updated on every append, but must never be deleted or truncated.
NEVER_DELETED = ("audit_auditchainhead",)
# Schema history belongs to the migration role.
READ_ONLY = ("django_migrations",)


def statements(role: str, database: str) -> list[sql.Composable]:
    who, db = sql.Identifier(role), sql.Identifier(database)
    plan: list[sql.Composable] = [
        sql.SQL("GRANT CONNECT ON DATABASE {db} TO {who}").format(db=db, who=who),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {who}").format(who=who),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {who}").format(who=who),
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {who}").format(who=who),
    ]
    for table in APPEND_ONLY:
        plan.append(
            sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON {table} FROM {who}").format(
                table=sql.Identifier(table), who=who
            )
        )
    for table in NEVER_DELETED:
        plan.append(
            sql.SQL("REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON {table} FROM {who}").format(
                table=sql.Identifier(table), who=who
            )
        )
    for table in READ_ONLY:
        plan.append(
            sql.SQL("REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON {table} FROM {who}").format(
                table=sql.Identifier(table), who=who
            )
        )
    return plan


class Command(BaseCommand):
    help = "Grant the application database role least-privilege access (run as the owner role, after migrate)."

    def add_arguments(self, parser):
        parser.add_argument("--role", required=True, help="PostgreSQL role the web and worker processes use.")
        parser.add_argument("--dry-run", action="store_true", help="Print the statements without running them.")

    def handle(self, *args, role, dry_run, **options):
        connection.ensure_connection()
        raw = connection.connection
        database = connection.settings_dict["NAME"]
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", [role])
            row = cursor.fetchone()
            if row is None:
                raise CommandError(
                    f'Role "{role}" does not exist. Create it first (infrastructure/postgres/init/10-app-role.sh).'
                )
            if row[0]:
                raise CommandError(f'Role "{role}" is a superuser; the application must not connect as one.')
            cursor.execute("SELECT current_user")
            if cursor.fetchone()[0] == role:
                raise CommandError("Run this as the owner role, not as the application role it is restricting.")
            cursor.execute("SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tableowner = %s LIMIT 1", [role])
            if cursor.fetchone():
                raise CommandError(f'Role "{role}" owns tables; an owner can bypass these restrictions.')

            for statement in statements(role, database):
                text = statement.as_string(raw)
                self.stdout.write(text)
                if not dry_run:
                    cursor.execute(text)
        self.stdout.write(
            self.style.SUCCESS("Dry run: nothing changed." if dry_run else f'Privileges applied to "{role}".')
        )
