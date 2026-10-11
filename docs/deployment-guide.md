# Deployment guide

How to run the production-oriented stack (`docker-compose.prod.yml`). This is a **starting point, not a certification**:
read [known-limitations.md](known-limitations.md) first, especially the key-custody and single-host points. The stack was
built and exercised with the smoke test, a real-browser test and a load test on one workstation
([test-report.md](test-report.md)); it has not been run on a public host.

## What you get

```
internet -> web (nginx, TLS) -> backend (Daphne/Django) -> db (PostgreSQL) / redis
                                worker (imports, expiry)
```

Only `web` publishes ports. `db` and `redis` live on a private network with no outside route; `backend` and `worker` also
join an outbound-only network to send email. Containers run unprivileged with read-only filesystems, no capabilities and
resource limits. Three database roles separate administration, migrations and the running application.

## Before you start

1. A host with Docker Engine and Compose v2, and DNS for the name users will type.
2. A **TLS certificate** and key for that name, from your CA or Let's Encrypt. Put them in `deploy/certs/tls.crt` (include
   the chain) and `deploy/certs/tls.key`. The directory is git-ignored. For a local trial only, `./infrastructure/scripts/make_dev_cert.sh`
   makes a self-signed pair.
3. An **SMTP relay** for invitations and password resets.
4. A plan for the **encryption keys** (below).

## Configure

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Edit every value. Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and keys with
`python -c "import base64,os; print('1:' + base64.urlsafe_b64encode(os.urandom(32)).decode())"` (three *different* keys for
`SV_VAULT_KEK_KEYS`, `SV_MFA_ENCRYPTION_KEYS`, `SV_BLIND_INDEX_KEYS`). Important settings:

| Setting | Notes |
|---|---|
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL` | Must match the public name and scheme exactly (`https://vault.example.com`). The app also refuses requests with any other `Host`. |
| `POSTGRES_PASSWORD`, `SV_OWNER_DB_PASSWORD`, `SV_APP_DB_PASSWORD` | Three different passwords for three roles. The superuser password stays in the database container; the owner password goes only to the one-shot `migrate` job. |
| `REDIS_PASSWORD` | URL-safe characters only. |
| `SV_METRICS_TOKEN` | Optional, 32+ characters. Unset means `/api/v1/metrics/` answers 404. |
| `SV_ENABLE_API_DOCS` | Leave `false`: Swagger UI loads assets from a CDN that the production CSP blocks. Use `docs/openapi.yaml`. |

`DEBUG` cannot be turned on from this file; the compose file fixes it to `false`, and the application refuses a weak `SECRET_KEY` when it is off.

## Start

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build --wait
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

The `migrate` job runs first (migrations as the owner role, then `apply_db_grants` for the application role) and exits; the
backend and worker start after it succeeds. Create the first administrator:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T -e SV_BOOTSTRAP_PASSWORD backend \
  python manage.py bootstrap_org --org-name "Your Company" --org-slug your-company --email admin@your-company.example --full-name "Admin Name"
```

(Export `SV_BOOTSTRAP_PASSWORD` in your shell first; do not put it on the command line.) Then open `https://your-host/`.

## Verify the deployment

`./infrastructure/scripts/smoke_prod.sh` builds a *separate* throwaway stack (project `sv-smoke`, its own env file, ports and
certificate, removed afterwards) and checks 87 properties: headers, TLS, which services are reachable, database role
privileges, the sign-in/vault/lockdown flow, WebSocket rules, container hardening, and that logs contain no secrets. Run it
on the host you deploy from. It never touches your real stack.

## Key custody (read this)

- `SV_VAULT_KEK_KEYS` wraps every organization's data key. **If it is lost, every stored secret is unrecoverable. If it leaks
  together with a database copy, every secret is exposed.** Store an offline copy separate from database backups and
  restrict who can read `.env.prod` and the container environment.
- The environment provider is the only one implemented. For production, implement a `KeyProvider` backed by your KMS/HSM
  (`backend/apps/vault/keys.py` defines the interface) and set `SV_VAULT_KEY_PROVIDER`; this is on the [roadmap](roadmap.md).
- **Rotation:** append a new version (`1:...,2:...`), restart, then
  `docker compose ... exec backend python manage.py rotate_vault_keys` (re-wraps data keys, rotates them, rebuilds blind
  indexes). Keep old versions in the keyring until it finishes. The command is covered by tests; plan a maintenance window
  the first time and take a backup first.

## Backups and restore

```bash
./infrastructure/scripts/backup.sh backups/                  # pg_dump (custom format) + SHA-256
./infrastructure/scripts/restore.sh backups/securevault-<stamp>.dump securevault_restore
```

`restore.sh` loads the dump into a **new** database next to the live one, re-applies privileges, and verifies the audit hash
chains with the application's own code; it never touches the live database. A dump holds ciphertext, not keys: back the keys up
separately and encrypt the dump (for example with `age` or `gpg`) before it leaves the host. Test restores regularly.

To cut over to a restored database: stop `backend` and `worker`, rename the databases
(`ALTER DATABASE securevault RENAME TO securevault_old; ALTER DATABASE securevault_restore RENAME TO securevault;`), start them
again. Keep the old database until you have verified the result.

## Operate

| Need | How |
|---|---|
| Logs | `docker compose ... logs -f backend` (JSON, one line per request, with request id); nginx logs paths only |
| Health | `GET /api/v1/health/` (public: database and Redis status, no details); container healthchecks cover every service |
| Metrics | Set `SV_METRICS_TOKEN`; scrape `http://backend:8000/api/v1/metrics/` from a container on the `edge` network with `Authorization: Bearer <token>` and a permitted `Host` header. nginx deliberately does not expose it |
| Update | `git pull`, then `up -d --build --wait` (migrations run automatically) |
| Scale the API | Run more backend containers behind nginx (WebSockets already fan out through Redis); each process handles roughly one request at a time, see [test-report.md](test-report.md) |
| Verify audit integrity | `... exec backend python manage.py verify_audit_chain` |
| Worker down | Imports stay *queued* and the UI says so. A crashed worker is restarted by Docker; a *stalled* one is only reported `unhealthy` (plain Docker does not restart unhealthy containers), so alert on `docker ps` health or use an orchestrator |
| Redis down | Signed-in users keep working (general rate limits pause, edge limits remain); sign-in answers 503 until it returns; the real-time channel reconnects automatically |
| Database down | Clean 503s with `Retry-After`; nothing is lost |

## Hardening checklist (do these for a real deployment)

- [ ] CA-issued certificate, renewal automated, OCSP stapling enabled in `infrastructure/nginx/conf.d/default.conf`.
- [ ] Decide on HSTS preloading deliberately (not enabled by default).
- [ ] Firewall: only 80/443 reachable; SSH restricted.
- [ ] KMS-backed key provider; keys not readable from the container environment.
- [ ] Encrypted, off-host backups and a tested restore.
- [ ] Log shipping and alerting (failed sign-ins, lockdown, `sv_open_alerts`, `sv_database_up`).
- [ ] SMTP credentials with a sending-only account; SPF/DKIM for the sender domain.
- [ ] An independent security review before holding real production secrets.
