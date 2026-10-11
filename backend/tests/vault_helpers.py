"""Shared helpers for vault tests."""

from django.db import connection

CREDENTIALS = "/api/v1/vault/credentials/"
NOTES = "/api/v1/vault/notes/"

# Contains every character class so it passes the default org policy (14+, upper, number, symbol).
STRONG_SECRET = "Xq7!Plaintext-Marker-9137"
OTHER_SECRET = "Zk4#Another-Marker-5528!"


def create_credential(client, **overrides):
    payload = {"title": "Prod DB", "username": "svc_app", "password": STRONG_SECRET, **overrides}
    return client.post(CREDENTIALS, payload, format="json")


def create_note(client, **overrides):
    payload = {"title": "Runbook", "content": "root token: s3cr3t-note-body-8841", **overrides}
    return client.post(NOTES, payload, format="json")


def dump_database_text() -> str:
    """Every cell of every table as one string, to prove a value is stored nowhere in plaintext."""
    parts: list[str] = []
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            cursor.execute(f'SELECT * FROM "{table}"')  # noqa: S608 - table names come from the catalog
            for row in cursor.fetchall():
                parts.append(" ".join("" if cell is None else str(cell) for cell in row))
    return "\n".join(parts)
