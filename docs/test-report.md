# Test report

Actual results, from runs made on **11 October 2026** on one Windows 11 workstation (Docker Desktop, Python 3.13, Node 22,
Edge 155 for the browser test). Commands to reproduce each item are in [testing-guide.md](testing-guide.md). Nothing here is an
independent audit; where something was not tested, that is said.

## Summary

| Check | Result |
|---|---|
| Backend tests (pytest) | **436 passed**, 0 failed (default connection mode) |
| Backend tests with the production connection pool (`SV_DB_POOL=true`) | **436 passed** |
| Backend line coverage (`apps`, `core`) | **96%** (5,197 statements, 201 not executed) |
| Frontend tests (Vitest), 12 files | **93 passed** (3 consecutive runs) |
| Type check, lint, format, production build | clean (`tsc`, `ruff check`, `ruff format --check`, `vite build`) |
| Migrations match the models | `makemigrations --check`: no changes |
| OpenAPI schema | valid with `--fail-on-warn`; 99 operations; committed file matches the code (tested) |
| Production smoke test (`smoke_prod.sh`) | **87 passed**, 0 failed, from a cold start |
| Real-browser end-to-end (Edge) | **9 passed**, 0 console errors or CSP violations |
| Django deployment checklist (`check --deploy`) | no issues (test `test_django_deployment_checklist_has_no_warnings`) |
| `pip-audit` (Python dependencies) | no known vulnerabilities |
| `npm audit` (frontend prod + dev; e2e) | 0 vulnerabilities |
| `gitleaks` over all git history | clean after allow-listing test fixtures (see below) |
| GitHub Actions workflow | `actionlint`: no findings. **Not executed on GitHub**; every step was run locally |

### Backend tests by area

| Area | Modules (tests) |
|---|---|
| Accounts, auth, MFA, passwords, invitations | auth (15), mfa (17), passwords (12), invitations (12), user_admin (8), user_model (7), bootstrap (3) |
| Tenancy, permissions, policy, catalog | permissions_and_tenancy (10), departments (6), services_catalog (10), policies (8) |
| Vault and crypto | vault_api (41), vault_encryption (15), vault_notes (7), vault_rotation (10), crypto (14), strength (30) |
| Sharing | sharing (26), sharing_concurrency (3), share_access_batch (3), access_requests (14) |
| Zero trust | devices (17), lockdown (13), realtime (5), notifications (4) |
| Audit, imports, reports | audit (22), imports (11), reports (20), dashboard (3) |
| Operations and hardening | observability (16), resilience (18), production_settings (11), db_grants (5), query_counts (16), health (2), docs_current (2) |

Weakest covered modules: `core/request_context.py` 88%, `core/views.py` 89%, `apps/notifications/consumers.py` 90%,
`apps/reports/datasets.py` 90%, `apps/sharing/services.py` 90%. Migrations and boilerplate excluded.

## Criteria from the requirements, and the evidence

| # | Requirement | Evidence |
|---|---|---|
| 1 | Credentials encrypted before persistence | `test_stored_row_holds_only_ciphertext_and_metadata`, `test_data_key_is_stored_only_wrapped`, `test_every_encryption_uses_a_fresh_nonce_and_ciphertext` |
| 2 | Database inspection finds no plaintext | `test_plaintext_secret_is_stored_nowhere_in_the_database` scans every cell of every table; `test_database_scan_would_catch_plaintext` proves the scan can find it |
| 3 | Unauthorized users cannot reveal or modify | sharing and vault API tests; `test_lockdown_blocks_decryption_for_everyone_including_administrators` |
| 4 | Organization boundaries | `test_other_organization_records_return_404`, `test_cannot_reference_other_organization_objects`, `test_reports_never_include_other_organizations`, `test_ciphertext_is_bound_to_the_organization` |
| 5 | Users cannot exceed delegated permissions | `test_share_grant_can_delegate_within_its_own_bounds`, `test_delegation_depth_is_limited`, `test_approval_cannot_exceed_the_request` |
| 6 | Revoking a parent invalidates every descendant | `test_revoking_a_parent_invalidates_every_descendant`, `test_ancestor_chain_is_checked_even_if_a_descendant_row_was_missed` |
| 7 | Concurrent view-once: at most one success | `test_concurrent_view_once_reveals_allow_exactly_one_success` (real threads, real PostgreSQL) |
| 8 | Failed authorization does not consume a view-once grant | `test_failed_authorization_does_not_consume_a_view_once_grant` |
| 9 | Consumed view-once returns 410 | `test_view_once_is_consumed_by_the_first_reveal_and_then_gone`; browser test (second reveal shows "already been used") |
| 10 | Lockdown blocks decryption without WebSocket | `test_lockdown_is_enforced_even_when_realtime_delivery_is_down`, `test_a_session_that_slips_through_is_still_refused` |
| 11 | Untrusted devices denied when required | `test_untrusted_devices_are_blocked_when_policy_requires_trust` |
| 12 | Audit records contain no secrets | `test_metadata_with_secret_like_keys_is_redacted`, `test_the_secret_type_label_is_kept_but_secret_values_are_not`; smoke test and browser test read the audit log and find no secret |
| 13 | Imports report successes and failures | `test_import_reports_successful_and_failed_rows`, `test_retry_imports_fixed_rows_without_creating_duplicates`, hostile-file tests |
| 14 | Session invalidation and revocation | `test_global_lockdown_terminates_employee_sessions_and_keeps_administrators`, `test_change_password_keeps_this_session_and_ends_others`, `test_terminated_sessions_lose_their_socket` |
| 15 | Inputs validated, org permissions enforced | per-app API tests; `test_the_api_only_speaks_json` |
| 16 | Recovers from expected service failures | `tests/test_resilience.py` (18 tests: Redis, PostgreSQL, SMTP, channel layer, worker) |
| + | Concurrency, transaction rollback, permission changes, reconnect | concurrency module; `test_action_fails_closed_when_audit_write_fails` (rollback); `test_suspension_pauses_delegated_access_and_reactivation_restores_it`; frontend reconnect-with-backoff test and `test_websocket_closes_cleanly_when_the_channel_layer_is_down` |

## Mutation checks (tests that can fail)

A test that cannot fail proves nothing, so the rule each important test protects was temporarily broken and the tests rerun:

| Broken on purpose | Result |
|---|---|
| Report requests stop sending filters | 2 tests failed |
| Page-level access resolution evaluated with a clock ten years in the past | 2 tests failed |
| `apply_db_grants` stops revoking UPDATE/DELETE/TRUNCATE on the audit table | 3 tests failed |
| A fail-closed credential endpoint made to fail open | 4 tests failed |
| The general user throttle made to fail closed | 2 tests failed |
| Earlier in the project: owner scoping removed, ciphertext binding removed, reveal gate removed, advisory lock removed | each caused test failures (done during development; not re-run for this report) |

Each change was reverted afterwards; the final runs above are on the unmodified code.

## Browser end-to-end (Edge, production stack through nginx and TLS)

Nine checks: strict CSP and a rejected bad password; session cookie is HttpOnly, Secure and SameSite=Strict and invisible to page
scripts; a stored secret never appears in the list's DOM; reveal shows it, web storage never contains it, and closing the dialog
removes it from the DOM; an invitation link activates an account once and fails the second time; a view-once share reveals exactly
once; a lockdown started by an administrator reached the employee's connected browser **896 ms** later and the server refused the
administrator's own reveal; the audit log holds REVEAL and LOCKDOWN records and no secret; zero console errors or CSP violations
across the whole run.

## Performance and resource use

*All figures: one laptop running the stack, the load generator and everything else; a single backend process capped at one CPU;
synthetic users; no network latency. They show behavior and limits, not capacity.* Method: [testing-guide.md](testing-guide.md#load-test-scenarios-and-method).

### Lockdown propagation

| Path | Rounds | min | p50 | p95 | Under 1 s |
|---|---|---|---|---|---|
| Direct to Daphne, WebSocket over Redis (development stack) | 15 | n/a | 121 ms | 157 ms | 15/15 |
| Through nginx with TLS, Docker production stack | 15 | 265 ms | 305 ms | 437 ms | 15/15 |
| Real browser (one run, includes UI render) | 1 | | 896 ms | | 1/1 |

This is the time from the administrator's request (including password re-authentication, the database commit and the Redis
fan-out) until the connected client has the event. It is an upper bound for "connected clients are told". Enforcement does not wait
for it: it holds from the database commit.

### Concurrent users, reveals, audit queries, imports

20 virtual users for 30 s on the page-load mix (all requests returned 200):

| Endpoint | Requests | p50 | p95 | p99 |
|---|---|---|---|---|
| `GET /auth/me/` | 180 | 449 ms | 787 ms | 988 ms |
| `GET /dashboard/` | 180 | 724 ms | 1,167 ms | 1,389 ms |
| `GET /vault/credentials/` | 180 | 701 ms | 1,382 ms | 1,695 ms |
| `GET /notifications/unread-count/` | 180 | 580 ms | 1,331 ms | 1,568 ms |
| `GET /devices/` | 180 | 496 ms | 1,156 ms | 1,440 ms |

Aggregate throughput was about 28 requests/second, with the backend process at its CPU ceiling (peak 98%). The latency is
queueing: a single Daphne process runs synchronous views one at a time. This is the main scalability limit
([known-limitations.md](known-limitations.md)); scaling out was not tested.

Reveals (decrypt + audit write under a shared advisory lock): 254 successful reveals at the paced rate, p50 82 ms, p95 176 ms. One
user firing 40 reveals in a row got **30 successes and 10 × 429**: the per-user limit holds exactly.

Audit and reports on the load organization's audit chain (about 1,600 records by the end of the run):

| Request | p50 | p95 |
|---|---|---|
| Audit list (page 1 / filtered by action / searched / page 5) | 27-30 ms | 33-35 ms |
| Audit report as JSON | 28 ms | 31 ms |
| Audit report as CSV export | 72 ms | 75 ms |
| Verify the whole hash chain | 39 ms | 44 ms |

Imports: a 150-row workbook processed inside the request took 1.6 s (150/150 invited); a 1,000-row workbook was accepted in 98 ms,
queued, and the worker finished it in **13.7 s** (73 rows/s), 1,000/1,000 invited.

### Container resources during the load run

| Service | CPU avg | CPU peak | Memory peak |
|---|---|---|---|
| backend | 31% | 98% (of 1 CPU) | 124 MiB |
| db | 8% | 30% | 80 MiB |
| worker | 3% | 47% (1,000-row import) | 93 MiB |
| redis | 2% | 5% | 7 MiB |
| web (nginx) | 0.3% | 3% | 12 MiB |

Image sizes: backend (production target) 438 MB, web (nginx + SPA) 82 MB.

### Query plans

`explain_hot_queries.py` on a scratch database with 100,000 audit records, 4,000 credentials, 4,000 shares and 200 users:

| Query | Plan (top scan) | Execution |
|---|---|---|
| Audit list, newest first | Index scan backward (org, created_at) | 0.12 ms |
| Audit filtered by action and date | Index scan backward (org, action, created_at) | 0.13 ms |
| Anomaly rule: a user's reveals in 10 minutes | Index scan backward (org, actor, created_at) | 0.11 ms |
| Dashboard reveals/copies per user, 7 days | Index scan backward (org, actor, created_at) | 0.26 ms |
| Access check: grants of a user on a credential | Index scan (credential, grantee) | 0.07 ms |
| Grants received by a user | Bitmap index scan (grantee) | 0.09 ms |
| Delegation tree of a credential | Index scan | 0.09 ms |
| Expiry sweep | Index scan (org, expires_at) | 0.06 ms |
| **Credential list (owned or shared)** | **Sequential scan** on credentials + bitmap scan on shares | 1.08 ms |

The last one is the exception: the `OR` between "owned" and "shared with me" defeats the indexes. It is fast at this size and
listed as a future rewrite for very large organizations.

### Query counts

`tests/test_query_counts.py` seeds 3 rows, counts the queries a list endpoint issues, adds up to 12 rows and counts again: 16 cases
(credentials, shared credentials, shares both directions, access requests both boxes, notifications, devices, alerts, audit log,
employees, departments, six reports, dashboard). All are constant now.

## Backup and restore drill

On the running production stack: `backup.sh` produced a 549 KB custom-format dump with a SHA-256 file; `restore.sh` loaded it into a
new database, re-applied privileges and verified the audit chains of all six organizations (the largest 1,639 records): all OK.
A restored credential then **decrypted with the production keys**. The live database was not touched. Tested once, on one machine.

## Problems this testing found (and what was done)

Reported because honest results include the defects:

| Found by | Problem | Fix |
|---|---|---|
| Inspecting the dev database | **Connection leak**: persistent connections piled up under Daphne (about one idle connection per minute, never reused); at the default limit the database would have refused connections after hours | `CONN_MAX_AGE=0`; pooled connections in production. After the fix: 1 connection an hour later |
| `test_query_counts` | **N+1 in the shared-credential list** (2 extra queries per shared credential) | Page-level access resolution with an equivalence test against the per-credential path |
| Reviewing the mail code | **Account-enumeration oracle**: if SMTP failed, password reset returned 500 for real accounts and 202 for unknown ones | Delivery failures logged, never raised; tested |
| Failure-injection tests | **Redis outage = total API outage**, including an administrator's lockdown | Defined policy: general throttles fail open, credential endpoints fail closed with 503 |
| Smoke test | **Query strings in logs** from Daphne's and nginx's default access logs (search terms) | Both replaced; zero occurrences afterwards |
| Smoke test | Self-signed certificate script silently failed under Git Bash (path rewriting); nginx could not start | Fixed and the script now reports errors |
| Database test | Raw connections to `localhost` took ~4 s each on Windows (IPv6 first); a test seemed hung | `127.0.0.1` in `.env.example`; explicit timeouts in tests |
| Reading the generated audit output | `secret_type` was redacted although it is only a label | Narrow exemption; test |
| gitleaks | 7 findings, all test fixtures (shared test password, strength-vector samples) | Allow-listed by path only; real secrets elsewhere still trip it |
| Frontend suite | An intermittent failure under parallel load (lazy-loaded page vs 1 s wait) | Longer async query ceiling; 3 consecutive green runs |
| Reading the dev container | Development emails could not be written (directory not writable by the unprivileged user) | Image creates the directory |
| Drafting the docs | A claim that the worker healthcheck restarts a stalled worker (Docker does not) | Claim corrected |

## What was not tested

Real SMTP delivery; a CA-issued certificate; a public host; a KMS; more than one backend replica; Firefox and Safari; screen
readers; sustained load (the runs were minutes long); failure of the host itself; any attack by an independent party.
