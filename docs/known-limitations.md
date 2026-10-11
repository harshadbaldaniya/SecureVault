# Known limitations

What SecureVault does **not** do, does only partly, or has not been shown to do. Read this before trusting it with
anything real. Items are grouped by how much they matter; the roadmap ([roadmap.md](roadmap.md)) orders the fixes.

## Security claims it cannot make

- **Not zero-knowledge.** The server decrypts secrets and holds the key-encryption key. Anyone with the database *and* the key
  material, or control of the running server, can read everything. ([security-model.md](security-model.md))
- **Key custody is basic.** Keys come from environment variables. A `KeyProvider` interface exists, but no KMS/HSM provider is
  implemented. Losing the KEK loses all stored secrets; there is no recovery path by design.
- **No independent review.** It has not been penetration-tested, audited or certified, and the threat model was written by the
  developers. "Tests pass" and "scans are clean" are not the same as "secure".
- **View-once does not prevent copying.** It limits how many times *SecureVault displays* a secret. Screenshots, photographs and
  manual copying are out of reach, and the UI says so.
- **Device identity is a signal, not proof.** The device cookie is random and server-issued, but fingerprint attributes are
  client-reported and forgeable, and a stolen cookie plus a matching profile looks like the trusted device. Anomaly detection is a
  small set of transparent rules (new device, new network, fingerprint mismatch, untrusted device, reveal bursts): it will miss
  careful attackers and flag legitimate travel.
- **Audit chain limits.** Tampering with or deleting records is detected, but someone who can write the whole table *and*
  recompute every later hash can forge a consistent chain. The head hash is not yet published anywhere outside the database.
- **A request that already passed every check** a few milliseconds before a lockdown commits can still finish; everything after
  the commit is refused.

## Availability and scale

- **One request at a time per backend process.** Daphne runs the synchronous Django views on a single thread. Measured on a laptop,
  one backend container saturated at about 28 requests/second of typical list endpoints (p50 450-720 ms at 20 concurrent users).
  Horizontal scaling (more backend containers) is designed for but **not tested**.
- **Single host.** The deployment is Docker Compose on one machine: one PostgreSQL, one Redis, no replication, failover or
  automated backups. Backups are a script you must schedule; restore was tested once, on one machine.
- **Scheduled work is not scheduled for you.** The worker handles queued imports and share-expiry notices. Purging archived items
  (`purge_archived_vault_items`, 30-day retention) needs a cron job or equivalent.
- **Docker does not restart an unhealthy (stalled) container**, only a crashed one. A stalled worker is reported but not
  restarted without extra tooling.
- During a Redis outage, general rate limits pause (edge limits in nginx remain) and sign-in answers 503; people who are already
  signed in keep working.
- The "credentials I own or that are shared with me" list uses a sequential scan today (1 ms at 4,000 credentials); it would need
  a rewrite (for example a UNION) at hundreds of thousands per organization.
- Rate-limit counters and metrics are per process / per IP. Many users behind one NAT share an IP limit.

## Not verified

- **Real SMTP delivery.** Mail is tested with Django's in-memory/file/dummy backends and failure injection; no real relay, bounce
  handling or deliverability work (SPF/DKIM).
- **A real CA-issued certificate, a public host, a KMS, multiple replicas** have not been exercised.
- **Browsers:** the end-to-end test runs on Chromium-based browsers (Edge). Firefox and Safari are untested. Accessibility is
  supported by roles, labels and keyboard-reachable chart marks and checked with Testing Library, but there has been no automated
  axe audit or screen-reader session.
- The frontend component tests use a mocked API; the real-browser test covers the main flows (sign-in, store, reveal, invite,
  view-once, lockdown) but not TOTP enrolment, device approval or reports.
- Load numbers come from one laptop that also ran the load generator. They are not capacity forecasts.

## Product gaps

- No SSO (OIDC/SAML), SCIM provisioning, WebAuthn/passkeys, browser extension or mobile app.
- Imports accept `.xlsx` only (2 MB, 5,000 rows). Up to 200 rows are processed inside the request (about 1.6 s for 150 rows
  measured), larger files go to the worker (about 73 rows/s measured).
- No `Idempotency-Key` support: a retried "create credential" call creates a second credential. Other sensitive operations are
  protected by natural uniqueness.
- No data-retention policy for the audit trail and no erasure workflow. Because audit records are append-only, test
  organizations created in a database cannot be removed from it; drop the database instead.
- No password-breach (pwned-password) check; password strength is an entropy *estimate*, not a guarantee.
- Changing `DJANGO_SECRET_KEY` signs everyone out; there is no tooling for rotating database or Redis passwords.
- The Swagger UI loads its assets from a CDN, so it is disabled in production (the CSP blocks it); use `docs/openapi.yaml`.
- HSTS preloading and OCSP stapling are intentionally left for the operator to decide.

## Environment notes

- On Windows with Docker Desktop, `localhost` tries IPv6 first and stalls several seconds per new connection; use `127.0.0.1`
  (the provided `.env.example` does).
- Development uses file-based email inside the backend container (`docker compose exec backend ls var/mail`).
