# Architecture

SecureVault is a multi-tenant credential and access management platform. This page describes how the pieces fit
together and why. Security properties and their limits are in [security-model.md](security-model.md) and
[known-limitations.md](known-limitations.md); the database is in [database-design.md](database-design.md).

## Components

```mermaid
flowchart LR
    Browser["Browser<br/>React + TypeScript SPA"]
    subgraph edge["Edge (docker network: edge)"]
        Nginx["nginx (unprivileged)<br/>TLS, CSP/headers, rate limits,<br/>static SPA"]
    end
    subgraph app["Application"]
        Daphne["Daphne (ASGI)<br/>Django + DRF + Channels"]
        Worker["Worker<br/>imports, share expiry"]
    end
    subgraph data["Data (docker network: data, no outside route)"]
        PG[("PostgreSQL 16")]
        Redis[("Redis 7<br/>throttles, cache, channel layer")]
    end
    KEK["Key material<br/>(environment / KMS provider)"]

    Browser -- "HTTPS /api" --> Nginx
    Browser -- "WSS /ws/events" --> Nginx
    Nginx -- "HTTP, X-Forwarded-*" --> Daphne
    Daphne --> PG
    Daphne --> Redis
    Worker --> PG
    Daphne -. "reads keys" .-> KEK
    Worker -. "reads keys" .-> KEK
```

| Part | Technology | Responsibility |
|---|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind, React Router, React Query, react-hook-form + zod | Presentation only. Never decides authorization; hides what the server would refuse. Holds no secret beyond a few seconds in component state. |
| Edge | nginx (unprivileged) | TLS, security headers and CSP, per-IP rate limits on sign-in paths, static files, reverse proxy for `/api/` and `/ws/`. Does not route `/api/v1/metrics/`. |
| API | Django 5.2, DRF, Daphne | Authentication (cookie sessions + CSRF), authorization, encryption, audit, all business rules. |
| Real time | Django Channels over Redis | Notifications and lockdown push. **A notification channel only**: every rule is also enforced by the API. |
| Worker | `manage.py run_worker` | Queued Excel imports; share-expiry notifications. Claims jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, so several workers can run. |
| Database | PostgreSQL 16 | System of record; advisory locks for concurrency; trigger for append-only audit. |
| Redis | Redis 7 | Rate-limit counters, login lockout counters, Channels groups. Holds no secrets and nothing that cannot be lost. |

Not used, deliberately: Kubernetes, a message broker, microservices. The workload is small and the existing pieces
(PostgreSQL row locking, a polling worker) are enough; see [roadmap.md](roadmap.md) for when that would change.

## Backend module boundaries

```mermaid
flowchart TB
    core["core<br/>access gate, permissions, crypto, tenancy,<br/>errors, throttling, logging, metrics"]
    org[organizations] --- acc[accounts]
    acc --- dep[departments]
    acc --- pol[policies]
    vault["vault<br/>keys, encryption, credentials, notes"]
    share["sharing<br/>grants, delegation, revocation"]
    req[access_requests]
    dev["devices<br/>trust, anomaly rules"]
    lock[lockdown]
    aud["audit<br/>hash-chained, append-only"]
    notif[notifications]
    imp[imports]
    rep["reports<br/>reports, exports, dashboard"]

    vault --> core
    share --> vault
    req --> share
    dev --> core
    lock --> core
    vault --> aud
    share --> aud
    acc --> aud
    lock --> aud
    lock --> notif
    imp --> acc
    rep --> aud
```

Rules that keep it maintainable:

- Views are thin; business rules live in `services.py` functions that run inside a transaction.
- Every list is built from an organization-scoped queryset (`core.tenancy`). A foreign id behaves like a missing one (404),
  and the attempt is audited as DENIED.
- Cross-cutting zero-trust checks register themselves with `core.access_gate` from each app's `ready()`, in
  `INSTALLED_APPS` order (see below).

## The zero-trust gate

Authentication is never enough to reveal a secret. Every sensitive action (`REVEAL`, `COPY`, `EDIT`, `SHARE`,
`DELETE`) goes through `core.access_gate.authorize(user, resource, action)`:

```mermaid
flowchart TD
    A["authorize(user, resource, action)"] --> B{"1. Account ACTIVE<br/>and organization ACTIVE?"}
    B -- no --> X["Deny + audit DENIED"]
    B -- yes --> C{"2. Same organization?"}
    C -- no --> X
    C -- yes --> D{"3. Action in resource.permissions_for(user)?<br/>owner, or a live grant whose whole ancestor chain is live"}
    D -- no --> X
    D -- yes --> E{"Sensitive action?"}
    E -- no --> OK["Allow"]
    E -- yes --> F{"4. Device trust<br/>(if the policy requires it)"}
    F -- fails --> X
    F -- passes --> G{"5. Anomaly hold<br/>(if the policy blocks on high risk)"}
    G -- fails --> X
    G -- passes --> H{"6. Emergency lockdown<br/>covering this user?"}
    H -- yes --> L["423 Locked"]
    H -- no --> OK
```

Roles never appear in step 3: an organization administrator has no special access to a secret. Roles only grant
*administrative* permissions (manage users, view audit, activate lockdown), listed in `core.permissions`.

## Reveal, step by step

```mermaid
sequenceDiagram
    participant U as Browser
    participant A as API (Django)
    participant DB as PostgreSQL
    U->>A: POST /vault/credentials/{id}/reveal/ (session cookie + CSRF header)
    A->>A: IsActiveMember: account, organization, MFA enrollment, lockdown
    A->>A: access gate (permissions, device trust, anomaly hold, lockdown)
    A->>DB: BEGIN
    A->>DB: pg_advisory_xact_lock_shared(credential)
    A->>DB: re-check the grant under the lock (a revocation may have committed)
    A->>A: AES-256-GCM decrypt (AAD binds org, kind, record, field)
    A->>DB: view-once? atomic compare-and-set burned_at
    A->>DB: append audit record (same transaction)
    A->>DB: COMMIT
    A-->>U: 200 {"password": ...}, Cache-Control: no-store
    Note over A,DB: Any failure before COMMIT leaves no burn and no audit row.<br/>A failed audit write fails the whole reveal.
```

Revocation takes the same advisory lock **exclusively**, so a reveal either sees the revocation or finishes before it;
there is no window in which a revoked grant still reveals. Concurrency tests cover this (see
[test-report.md](test-report.md)).

## Emergency lockdown

```mermaid
sequenceDiagram
    participant S as Security admin
    participant A as API
    participant DB as PostgreSQL
    participant R as Redis
    participant E as Employee browser (WebSocket)
    S->>A: POST /lockdown/activate/ (reason, password re-entry)
    A->>DB: BEGIN; insert LockdownState (active)
    A->>DB: COMMIT
    Note over A,DB: From this commit on, every sensitive API call is refused (423),<br/>whether or not any socket hears about it.
    A->>R: publish lockdown.activated (after commit, best effort)
    R-->>E: lockdown.activated, then close code 4423
    A->>DB: delete the affected users' sessions
    E->>E: shows the lockdown screen / sign-in
```

Phase order matters: the state is committed first, the notification is sent second, sessions are killed last. If Redis
is down the push is lost but the lockdown still holds. Measured propagation is in [test-report.md](test-report.md).

## Real-time channel

`/ws/events/` authenticates with the same session cookie, checks the `Origin` header against `ALLOWED_HOSTS`, and
re-checks the account and any lockdown at handshake, so reconnecting cannot bypass a lockdown. Refusals are
*accept-then-close* with an application code (4401 unauthenticated, 4423 lockdown, 1011 real-time layer unavailable);
rejecting the handshake would show up as an indistinguishable 1006 in browsers.

## Deployment topology

```mermaid
flowchart LR
    Internet --> web
    subgraph "docker-compose.prod.yml"
        web["web<br/>nginx :443/:80"]
        backend
        worker
        migrate["migrate<br/>(one-shot)"]
        db[(db)]
        redis[(redis)]
    end
    web -->|edge| backend
    backend -->|data| db
    backend -->|data| redis
    worker -->|data| db
    migrate -->|data| db
    backend -.->|egress: SMTP| Internet
    worker -.->|egress: SMTP| Internet
```

Three database identities: a bootstrap superuser known only to the database container, an owner role used only by the
one-shot `migrate` job, and a restricted application role for everything that runs continuously (cannot alter the
schema or UPDATE/DELETE/TRUNCATE the audit trail). See [deployment-guide.md](deployment-guide.md).

## Scaling notes (measured, not promised)

Each Daphne process runs synchronous DRF views on one thread, so one process serves roughly one request at a time.
On a laptop, one backend container handled about 28 requests/second of typical list endpoints before queueing
(p50 450-720 ms at 20 concurrent users; zero errors). Scale by running more backend containers behind nginx
(WebSockets already fan out through Redis). No horizontal-scaling test has been run. Details: [test-report.md](test-report.md).
