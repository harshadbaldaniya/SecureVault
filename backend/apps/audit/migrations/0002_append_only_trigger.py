"""Database-level append-only enforcement for audit_auditlog.

Blocks UPDATE and DELETE for every database role, including raw SQL that bypasses
the ORM. The table owner can still disable the trigger or TRUNCATE the table; in
production the application must connect as a non-owner role without TRUNCATE privilege
(see docs/security-model.md). TRUNCATE is not trigger-blocked so that Django's test
database flush keeps working.
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION audit_auditlog_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditlog is append-only (% blocked)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_append_only
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_auditlog_block_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_auditlog_append_only ON audit_auditlog;
DROP FUNCTION IF EXISTS audit_auditlog_block_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
