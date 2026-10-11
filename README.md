# SecureVault

A multi-tenant credential and access-management platform: an encrypted vault for passwords, API keys and secure notes, with
delegated sharing, device trust, anomaly alerts, emergency lockdown, a tamper-evident audit trail, Excel onboarding and
compliance reports.

> **Status: a completed MVP, not a certified product.** It has extensive automated tests and a real-browser test, but no
> independent security review or penetration test, and it has not run on a public host. Read
> [docs/known-limitations.md](docs/known-limitations.md) before trusting it with real secrets.
> It is **server-side envelope encryption, not zero-knowledge**: the server can decrypt what it stores.

## What it does

- **Encrypted vault.** Credentials and notes are encrypted with AES-256-GCM under per-organization data keys that are wrapped by
  a key held outside the database. A database copy alone is useless; secrets are write-only through the API and revealed one at a
  time, with authorization, rate limiting and an audit record.
- **Delegated access.** Share with a person (view, edit, or re-share), optionally view-once, with expiry. Revoking a grant revokes
  everything delegated from it, immediately. Access requests let people ask the owner.
- **Zero-trust checks on every sensitive action.** Account and organization status, tenancy, grant chain, device trust,
  anomaly hold and lockdown are re-evaluated on each reveal, copy, edit and share. Roles never grant access to a secret.
- **Devices and anomalies.** Server-issued device identity, administrator approval, rule-based alerts (new device or network,
  fingerprint mismatch, reveal bursts).
- **Emergency lockdown.** Organization-wide or per person, enforced by the server; connected browsers are told within a second
  (measured: p50 305 ms through nginx and TLS).
- **Audit.** Append-only, hash-chained, fail-closed; no secret ever appears in it.
- **Operations.** Excel import with hardened parsing, notifications and real-time events, dashboard, six reports with CSV, Excel
  and PDF export, MFA (TOTP + recovery codes), password reset, invitations.

## Quick start (development)

```powershell
git clone https://github.com/harshadbaldaniya/SecureVault.git
cd SecureVault
py infrastructure/scripts/init_env.py          # private .env with fresh random secrets
docker compose up -d --build --wait            # PostgreSQL, Redis, backend on http://127.0.0.1:8000
# create the first administrator (see docs/setup-guide.md for the password step), then:
cd frontend; npm ci; npm run dev               # http://localhost:5173
```

Full instructions, troubleshooting and the test commands: [docs/setup-guide.md](docs/setup-guide.md).

## Technology

React 19 · TypeScript · Vite · Tailwind · React Router · React Query · react-hook-form + zod  |  Python 3.13 · Django 5.2 ·
Django REST Framework · Django Channels (Daphne/ASGI)  |  PostgreSQL 16 · Redis 7  |  Docker Compose · nginx · GitHub Actions.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | Django project: `apps/` (accounts, vault, sharing, devices, lockdown, audit, imports, reports, ...), `core/` (access gate, crypto, permissions, logging, metrics), `tests/` |
| `frontend/` | React SPA and its tests |
| `e2e/` | Real-browser end-to-end test |
| `infrastructure/` | nginx config, PostgreSQL init, smoke/backup/restore scripts, load-test tooling |
| `docs/` | Everything below |
| `docker-compose.yml` / `docker-compose.prod.yml` | Development stack / production-oriented stack |

## Documentation

| Document | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, the zero-trust gate, reveal and lockdown sequences, deployment topology |
| [docs/database-design.md](docs/database-design.md) · [er-diagram.md](docs/er-diagram.md) | Schema, constraints, locking, the audit trail (ER diagrams are generated from the models) |
| [docs/security-model.md](docs/security-model.md) | What is protected and how, and what is not |
| [docs/threat-model.md](docs/threat-model.md) | Threats, mitigations, evidence, residual risk |
| [docs/api-documentation.md](docs/api-documentation.md) · [openapi.yaml](docs/openapi.yaml) | Conventions, errors, endpoint catalogue |
| [docs/setup-guide.md](docs/setup-guide.md) | Development setup |
| [docs/deployment-guide.md](docs/deployment-guide.md) | Production-style deployment, key custody, backup and restore |
| [docs/testing-guide.md](docs/testing-guide.md) | How to run every kind of test and the load-test method |
| [docs/test-report.md](docs/test-report.md) | **Actual results**, including problems found and fixed |
| [docs/known-limitations.md](docs/known-limitations.md) | What it does not do or has not been shown to do |
| [docs/roadmap.md](docs/roadmap.md) | Prioritized next steps |

## Security notes for contributors

- Never commit `.env`, keys or certificates (all are git-ignored); `.env.example` and `.env.prod.example` contain placeholders only.
  CI scans the full history with gitleaks.
- There is no default administrator and no secret in the code. Do not add either.
- Do not log request bodies, headers, cookies or secrets; the log formatter only emits allow-listed fields.
- New endpoints must use organization-scoped querysets and the access gate; the tenancy and query-count tests catch common drift.
