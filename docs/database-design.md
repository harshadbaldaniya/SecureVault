# Database design

PostgreSQL is the system of record. The entity-relationship diagrams are **generated from the Django models**
([er-diagram.md](er-diagram.md), produced by `python manage.py er_diagram`); a test fails if that file drifts from the
code. This page explains the parts the diagrams cannot: constraints, keys, locks and why they are there.

All primary keys are UUIDs except the audit tables (sequential, by design) and a few small internal tables. All
timestamps are timezone-aware UTC. Schema changes are made only through Django migrations; the production
application role cannot alter the schema.

## Tenancy

Every business row carries `organization_id`. Querysets are always built from the caller's organization
(`core.tenancy.OrgScopedQuerysetMixin`), foreign keys supplied by clients are validated against the organization
(`OrgScopedPrimaryKeyRelatedField`), and cross-organization ids return 404 and an audited DENIED record. Several
uniqueness rules are per organization (department code, service name), so two tenants can use the same names.

## Encryption-related tables

| Table / column | What it holds | Why it looks like this |
|---|---|---|
| `vault_organizationkey` | One **wrapped** data key (DEK) per organization and version, plus `is_active` | The DEK is stored only encrypted by the key-encryption key (KEK), which lives outside the database. A partial unique index allows only one active key per organization. |
| `vault_credential.secret_ciphertext`, `key_version` | `v<version>:<nonce>:<ciphertext>` from AES-256-GCM | A fresh 12-byte nonce per encryption. The authenticated data (AAD) binds organization, kind, record id and field, so a ciphertext copied to another row or tenant fails to decrypt. |
| `vault_credential.blind_index`, `blind_index_version` | HMAC-SHA-256 of the secret under a **separate** key, prefixed with the organization id | Lets the server count reused passwords per owner without decrypting. It is deterministic by design: it reveals equality and frequency of secrets within one owner's credentials and nothing else. Never exposed by the API. |
| `accounts_totpdevice.secret_encrypted` | TOTP seed, AES-GCM under the MFA keyring | A database copy alone cannot generate codes. |
| `accounts_recoverycode.code_hash`, `*_token_hash` | SHA-256 of high-entropy random tokens | Invitation and reset tokens (256 bits) and MFA recovery codes (80 bits, single use) are shown once and only their hash is stored; with that much randomness a fast hash is appropriate. |
| `accounts_user.password` | Argon2id hash | Django's password hasher. |

A test dumps every cell of every table and asserts the plaintext of a stored secret appears nowhere; a negative control
proves the scan would find it (`test_plaintext_secret_is_stored_nowhere_in_the_database`).

## Constraints that enforce rules

| Rule | Mechanism |
|---|---|
| Email unique, case-insensitively | Lower-cased on save plus a unique constraint on `Lower(email)` |
| A user is never a grantor and grantee of the same share | `CHECK grantor <> grantee` (`share_not_to_self`) |
| View-once grants are view-only | `CHECK NOT is_view_once OR permission = 'VIEW'` |
| Delegation is at most 5 levels deep, and `depth` agrees with `parent_share` | `CHECK depth <= 5`, `CHECK (parent IS NULL AND depth = 0) OR (parent IS NOT NULL AND depth > 0)` |
| One open grant per (credential, grantor, grantee) | Partial unique index where not revoked and not burned |
| One active organization-wide lockdown | Partial unique index (`one_active_global_lockdown`) |
| A user-scoped lockdown has a target; a global one does not | `CHECK` (`lockdown_target_matches_scope`) |
| One pending access request per user and credential | Partial unique index |
| Audit chain positions are unique | Unique (`chain_key`, `sequence`) |

Natural uniqueness is also what makes retries safe: a repeated "share with Bob" or "request access" cannot create a
duplicate, and a repeated invitation acceptance finds the token already used.

## Indexes

Indexes were added for the queries the application actually issues, and the hot paths were checked with
`EXPLAIN` on realistic data volumes ([test-report.md](test-report.md#query-plans)):

- `audit_auditlog (organization, created_at)`, `(organization, action, created_at)`, `(organization, actor_id, created_at)`,
  `(organization, target_type, target_id)`: the audit list, filters, the dashboard activity chart and the reveal-burst
  anomaly rule.
- `sharing_share (grantee, credential, revoked_at)`, `(credential, parent_share)`, `(organization, expires_at)`: access
  evaluation, the delegation tree and expiry sweeps.
- GIN indexes on `tags` for credentials and notes.

List endpoints are tested for **constant query count** as the number of rows grows
(`tests/test_query_counts.py`); that test found and fixed a per-row query pattern in the shared-credential list.

## Concurrency

Two mechanisms, both in PostgreSQL:

1. **Advisory locks** keyed by credential (`pg_advisory_xact_lock[_shared]`, namespace `0x5EC7`). Reveals and edits take
   the lock *shared*; grant creation and revocation take it *exclusive*. Plain row locks were tried first: with many
   concurrent readers, a revocation waited 23 s. With advisory locks it commits in under 3 s even under load, and the
   test asserts that.
2. **Atomic compare-and-set** for view-once consumption: `UPDATE ... SET burned_at = now() WHERE id = ... AND burned_at IS NULL
   AND revoked_at IS NULL AND expires_at > now()`; exactly one concurrent caller sees one affected row.

Cascading revocation is a recursive CTE `UPDATE ... RETURNING` over the delegation tree, so a parent's revocation and
every descendant's happen in one statement.

## The audit trail

`audit_auditlog` is append-only at three levels:

1. The Django model refuses `update()`/`delete()`.
2. A **PostgreSQL trigger** (`audit_auditlog_append_only`) raises on any `UPDATE` or `DELETE`, even from raw SQL.
3. The production application role has **no** `UPDATE`, `DELETE` or `TRUNCATE` on the table
   (`manage.py apply_db_grants`; verified by connecting as that role, `tests/test_db_grants.py` and the smoke test).
   This closes what the trigger cannot: an owner could drop the trigger or truncate the table, the application role
   cannot.

Each record hashes the previous record's hash together with its own content, per organization chain and one global chain.
`manage.py verify_audit_chain` and `GET /api/v1/audit-logs/verify/` recompute the chain; tampering with or deleting any
record (including the newest) is detected. **Limit:** someone who can write the table *and* recompute every later hash
can forge a consistent chain. Periodically publishing the head hash outside the database would close that (see
[roadmap.md](roadmap.md)).

## Backups

Logical backups with `pg_dump -Fc` (`infrastructure/scripts/backup.sh`). The dump contains ciphertext and wrapped keys,
not the KEKs; keep the key material backed up separately or the dump cannot be decrypted. Restore into a new database
and verify (`restore.sh`) is exercised in [test-report.md](test-report.md#backup-and-restore-drill).
