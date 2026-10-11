# Threat model

A working document, not a security assessment. It lists what could go wrong, what the code does about it, where the
evidence is, and what remains. It was written by the developers; it has **not** been reviewed by an independent security
professional (see [known-limitations.md](known-limitations.md)).

## Assets (most to least sensitive)

1. Stored secrets (passwords, API keys, secure-note contents).
2. Key material: the KEK keyring, MFA keyring, blind-index key, and the Django `SECRET_KEY`.
3. Authentication state: password hashes, TOTP seeds, recovery codes, sessions.
4. The audit trail (its integrity matters more than its secrecy).
5. Organization metadata: who exists, who shared what, device inventory.

## Actors

| Actor | Capability assumed |
|---|---|
| Anonymous internet user | Reaches nginx only; can send arbitrary requests |
| Authenticated employee | Valid session in one organization |
| Delegated grantee | Employee holding a share (possibly a chain) |
| Malicious employee / insider | Tries to exceed grants, hide actions, or exfiltrate in bulk |
| Administrator (Org/Security) | Administrative permissions, **no** automatic access to secrets |
| Another tenant | Authenticated in a different organization |
| Attacker with a database copy | Has a backup or a stolen volume, not the keys |
| Attacker with network position | Can observe or modify traffic between client and server |
| Attacker with a hijacked session | Holds a valid session cookie of a victim |

## Trust boundaries

Browser | nginx | Daphne/Django | PostgreSQL and Redis (private network) | key material (environment). The browser is never
trusted for roles, organization, permissions or device identity.

## Threats and mitigations

Evidence names are tests under `backend/tests/` unless stated; "smoke" is `infrastructure/scripts/smoke_prod.sh`, "e2e" is
the real-browser suite in `e2e/`.

| # | Threat | Mitigation | Evidence | Residual risk |
|---|---|---|---|---|
| 1 | Database copy exposes secrets | AES-256-GCM envelope encryption; keys outside the database | `test_plaintext_secret_is_stored_nowhere_in_the_database`, `test_data_key_is_stored_only_wrapped` | Database **and** keys together expose everything |
| 2 | Ciphertext swapped between rows or tenants | AAD binds org, kind, record, field | `test_ciphertext_is_bound_to_its_record`, `..._to_the_organization`, `test_tampered_ciphertext_is_rejected` | None known |
| 3 | Key reuse across purposes | Separate KEK / blind-index / MFA keys, validated at startup | `test_key_purposes_must_not_share_material` | Environment keys are only as safe as the host |
| 4 | Broken access control / IDOR / cross-tenant read | Org-scoped querysets; foreign ids are 404 and audited | `test_other_organization_records_return_404`, `test_cannot_reference_other_organization_objects`, `test_reports_never_include_other_organizations` | New endpoints must follow the pattern; the query-count and tenancy tests help catch drift |
| 5 | Admin reads a secret by role | Roles carry no secret access; gate has no role check | `test_lockdown_blocks_decryption_for_everyone_including_administrators` and the sharing tests | An admin can add *themselves* only via a grant by the owner, which is audited |
| 6 | Grantee exceeds delegated rights | Permission/expiry bounded by parent, depth limit | `test_share_grant_can_delegate_within_its_own_bounds`, `test_delegation_depth_is_limited`, `test_expiry_defaults_to_policy_and_cannot_exceed_it_or_be_in_the_past` | None known |
| 7 | Revoked access still works | Cascading revocation; ancestor chain checked on every use; exclusive advisory lock | `test_revoking_a_parent_invalidates_every_descendant`, `test_ancestor_chain_is_checked_even_if_a_descendant_row_was_missed`, `test_a_child_grant_cannot_survive_a_concurrent_parent_revocation` | None known |
| 8 | View-once reused via race | Atomic compare-and-set | `test_concurrent_view_once_reveals_allow_exactly_one_success`, `test_view_once_is_consumed_by_the_first_reveal_and_then_gone` | A recipient can still photograph or copy what they were shown |
| 9 | Credential stuffing / brute force | Lockout per hashed email, throttles, nginx limits, Argon2id | auth tests, `test_credential_entry_points_refuse_instead_of_losing_their_rate_limits` | Distributed low-rate attacks against many accounts are not detected specially |
| 10 | Session fixation / theft | Session rotation at sign-in; HttpOnly+Secure+SameSite=Strict cookie; server-side revocation | `test_login_rotates_session_key_to_prevent_fixation`; e2e cookie flags | A stolen *live* cookie works until it expires or is revoked; device trust can limit this |
| 11 | CSRF | Header+cookie token, Origin check, SameSite=Strict | `test_login_requires_csrf_token`, `test_authenticated_writes_require_csrf_token`; smoke "login without a CSRF token is refused" | None known |
| 12 | XSS steals secrets or session | React escaping, strict CSP (no inline/eval), HttpOnly cookie, secrets only in short-lived state | e2e: zero CSP violations, secret absent from DOM and storage after closing | A bug in a dependency that ships to the browser |
| 13 | Cross-site WebSocket hijacking | Origin validation + session auth at handshake | `test_unauthenticated_and_cross_origin_handshakes_are_refused`; smoke foreign-origin check | None known |
| 14 | Lockdown bypassed by reconnecting or offline socket | State enforced in the API; handshake re-checks lockdown | `test_lockdown_is_enforced_even_when_realtime_delivery_is_down`, `test_a_session_that_slips_through_is_still_refused` | None known |
| 15 | Audit tampering | Trigger + DB privileges + hash chain + fail-closed | `test_database_trigger_blocks_raw_sql_mutation`, `test_tampering_is_detected`, `test_deleting_the_newest_record_is_detected`, `tests/test_db_grants.py` | Full-table rewrite with recomputed hashes by a privileged actor |
| 16 | Secrets leak via logs or errors | Allow-listed log fields, redaction, generic 500/503 | `test_access_log_has_route_status_and_ids_but_never_query_strings_or_credentials`, `test_a_database_outage_is_a_503_that_names_nothing`; smoke greps all logs for every secret | Third-party library logging (monitored by the smoke test only) |
| 17 | Malicious spreadsheet (XXE, zip bomb, formula injection, privilege injection) | defusedxml, size/row caps, ZIP pre-checks, name checks, privileged roles rejected | `tests/test_imports.py` (e.g. `test_xml_entity_expansion_is_blocked_by_defusedxml`, `test_hostile_or_malformed_files_are_rejected`) | A parser vulnerability in openpyxl/defusedxml |
| 18 | CSV/Excel/PDF export injection or secret leakage | Neutralized cells, allow-listed columns | `tests/test_reports.py` (`test_no_report_or_export_contains_secret_material`) | Spreadsheet applications differ in what they execute |
| 19 | Account enumeration | Identical responses for reset and sign-in failures, including when mail fails | `test_reset_request_answers_identically_for_known_and_unknown_emails`, `test_mail_failure_does_not_reveal_which_accounts_exist` | Timing differences are not measured |
| 20 | Dependency vulnerabilities | Exact pins, audits in CI, Dependabot | `pip-audit`, `npm audit`: none found at the time of writing | New advisories appear daily; CI must keep running |
| 21 | Secrets committed to git | gitignore, placeholder templates, gitleaks in CI | gitleaks over full history: clean (test fixtures allow-listed) | A developer bypassing hooks |
| 22 | Compromised application host | Containers: non-root, read-only, no capabilities; restricted database role; separate networks | smoke hardening checks | Root on the host defeats all of it |
| 23 | Redis / SMTP / database outage causes unsafe behavior | Defined fail-open (general throttles) and fail-closed (credential endpoints) policies; 503 not 500 | `tests/test_resilience.py` | During a Redis outage general rate limits are off (edge limits remain) |
| 24 | Internal SSRF | The server fetches no user-supplied URL | code search: no outbound HTTP client in the application | Future features must keep this property |
| 25 | Replay / duplicate operations | Natural uniqueness (open grant per pair, pending request per user, single-use tokens), TOTP replay protection | sharing, access-request and MFA tests | No `Idempotency-Key` header for creates (a double-click can create two credentials) |

## Out of scope

Physical access, a malicious browser extension on a user's device, denial of service at network scale, legal and compliance
requirements, and the security of whatever KMS or SMTP provider an operator chooses.
