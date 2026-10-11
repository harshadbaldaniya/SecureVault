"""Least-privilege database role: the application can do its work but cannot rewrite history.

These tests create a real PostgreSQL login role, run `apply_db_grants` for it, then connect AS that role and try
the operations that must fail. Roles are cluster-wide, so the role is dropped again in a `finally`.
"""

import secrets
import socket
from io import StringIO

import psycopg
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from psycopg import errors, sql

pytestmark = pytest.mark.django_db(transaction=True)


def _ipv4(host: str) -> str:
    """Resolve to an IPv4 address. On Windows with Docker Desktop, trying ::1 first stalls until the timeout."""
    return socket.getaddrinfo(host or "127.0.0.1", None, socket.AF_INET)[0][4][0]


@pytest.fixture
def app_role():
    """A throw-away login role; yields (name, connect) where connect() opens a connection as that role."""
    name = f"sv_test_app_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    settings = connection.settings_dict
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE")
            .format(sql.Identifier(name), sql.Literal(password))
            .as_string(connection.connection)
        )

    def connect():
        return psycopg.connect(
            host=_ipv4(settings["HOST"]),
            port=settings["PORT"],
            dbname=settings["NAME"],
            user=name,
            password=password,
            autocommit=True,
            connect_timeout=5,
        )

    try:
        yield name, connect
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)).as_string(connection.connection))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)).as_string(connection.connection))


def denied(connection_, statement):
    with pytest.raises(errors.InsufficientPrivilege):
        connection_.execute(statement)


def test_the_application_role_can_work_but_cannot_rewrite_the_audit_trail(app_role):
    name, connect = app_role
    call_command("apply_db_grants", "--role", name, stdout=StringIO())

    with connect() as db:
        # Normal application work.
        db.execute("SELECT count(*) FROM accounts_user")
        db.execute("UPDATE accounts_user SET full_name = full_name WHERE false")
        db.execute("DELETE FROM sharing_share WHERE false")
        db.execute("SELECT count(*) FROM audit_auditlog")
        db.execute("UPDATE audit_auditchainhead SET last_sequence = last_sequence WHERE false")  # chain head moves
        db.execute("SELECT last_value FROM audit_auditlog_id_seq")  # needed to append

        # The audit trail is append-only for this role, independently of the trigger.
        denied(db, "UPDATE audit_auditlog SET reason = reason WHERE false")
        denied(db, "DELETE FROM audit_auditlog WHERE false")
        denied(db, "TRUNCATE audit_auditlog")
        denied(db, "DELETE FROM audit_auditchainhead WHERE false")
        denied(db, "TRUNCATE audit_auditchainhead")

        # Schema history and the schema itself are the migration role's business.
        denied(db, "INSERT INTO django_migrations (app, name, applied) VALUES ('x', 'y', now())")
        denied(db, "DELETE FROM django_migrations WHERE false")
        denied(db, "CREATE TABLE sv_rogue (id int)")
        denied(db, "DROP TABLE accounts_user")
        denied(db, "ALTER TABLE accounts_user ADD COLUMN rogue int")
        denied(db, "ALTER TABLE audit_auditlog DISABLE TRIGGER audit_auditlog_append_only")
        denied(db, "DROP TRIGGER audit_auditlog_append_only ON audit_auditlog")


def test_without_the_command_a_new_role_has_no_access_at_all(app_role):
    _, connect = app_role
    with connect() as db:
        denied(db, "SELECT count(*) FROM accounts_user")  # fail closed


def test_the_command_is_idempotent_and_repairs_over_broad_grants(app_role):
    name, connect = app_role
    with connection.cursor() as cursor:
        cursor.execute(f'GRANT ALL ON audit_auditlog TO "{name}"')  # an operator's mistake
    for _ in range(2):
        call_command("apply_db_grants", "--role", name, stdout=StringIO())
    with connect() as db:
        denied(db, "DELETE FROM audit_auditlog WHERE false")
        denied(db, "TRUNCATE audit_auditlog")


def test_dry_run_prints_the_plan_and_changes_nothing(app_role):
    name, connect = app_role
    out = StringIO()
    call_command("apply_db_grants", "--role", name, "--dry-run", stdout=out)
    text = out.getvalue()
    assert f'TO "{name}"' in text and "REVOKE UPDATE, DELETE, TRUNCATE" in text and "Dry run" in text
    with connect() as db:
        denied(db, "SELECT count(*) FROM accounts_user")


def test_the_command_refuses_unsafe_roles(app_role):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        owner = cursor.fetchone()[0]
    with pytest.raises(CommandError, match="does not exist"):
        call_command("apply_db_grants", "--role", "no_such_role_" + secrets.token_hex(3), stdout=StringIO())
    with pytest.raises(CommandError, match="superuser|owner role"):
        call_command("apply_db_grants", "--role", owner, stdout=StringIO())  # the current (owner) role
