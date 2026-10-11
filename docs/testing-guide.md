# Testing guide

Results are in [test-report.md](test-report.md). This page explains what the tests are, how to run each layer, and how the
performance numbers were measured.

## Layers

| Layer | Where | What it proves | Needs |
|---|---|---|---|
| Backend unit/API/security tests | `backend/tests/` (pytest) | Business rules, permissions, tenancy, encryption-at-rest, concurrency, audit integrity, resilience, query counts, production settings | PostgreSQL + Redis containers (`docker compose up -d`) |
| Frontend tests | `frontend/src/**/*.test.ts(x)` (Vitest + Testing Library) | Components and flows against a mocked API; accessibility roles; secrets kept out of the cache and DOM | Node |
| Production-stack smoke test | `infrastructure/scripts/smoke_prod.sh` | The built production images, nginx, roles and flows behave as claimed (87 checks) | Docker, openssl, curl, Node |
| Browser end-to-end | `e2e/` (playwright-core + system Edge/Chrome) | The real SPA against the real stack: CSP, cookies, reveal, invitation, view-once, lockdown | A running stack and a browser |
| Load and latency | `infrastructure/loadtest/`, `infrastructure/scripts/measure_lockdown_latency.mjs` | Response times, throttle behavior, resource use, lockdown propagation | A running stack |
| Query-plan review | `infrastructure/scripts/explain_hot_queries.py` | Hot queries use indexes at realistic volume | A scratch database |

## Backend

```powershell
cd backend
.\venv\Scripts\Activate.ps1
pytest -q                                    # everything
pytest -q tests/test_sharing_concurrency.py  # one module
pytest -q --cov=apps --cov=core              # with coverage
$env:SV_DB_POOL = "true"; pytest -q          # the connection mode production uses
ruff check . ; ruff format --check .
python manage.py makemigrations --check --dry-run
python manage.py spectacular --validate --fail-on-warn --file ../docs/openapi.yaml
```

Notes on how the suite is built:

- Tests use an in-memory cache and channel layer (`conftest.py`), so counters never leak between tests or into your Redis.
- Concurrency tests (`transaction=True`) run real threads against real PostgreSQL transactions; they assert *outcomes* (exactly one
  view-once success, no reveal after a revocation commits, revocation not starved), not timing luck.
- `tests/test_db_grants.py` creates a real PostgreSQL role, applies the production grants and connects **as that role** to prove
  what it cannot do.
- `tests/test_production_settings.py` starts Django in a subprocess with `DEBUG` off and runs `check --deploy`.
- `tests/test_query_counts.py` seeds a few rows, then more, and asserts the number of queries does not grow (N+1 detector).
- `tests/test_docs_current.py` fails when `docs/openapi.yaml` or `docs/er-diagram.md` is stale.
- **Mutation checks** (done by hand, not part of the suite): temporarily break the rule a test claims to protect (remove a
  `REVOKE`, skew a clock, drop a filter, make a fail-closed throttle fail open) and confirm the tests fail, then restore. A test that
  cannot fail proves nothing; the report lists the ones performed.

## Frontend

```powershell
cd frontend
npm test            # run once
npm run typecheck
npm run build
```

Shared fixtures keep browser and server in step: `shared/strength-vectors.json` (password-strength estimator, checked by both
sides) and `shared/audit-actions.json` (audit action list, checked by both sides).

## Production-stack smoke test

```bash
./infrastructure/scripts/smoke_prod.sh              # builds, checks, removes everything it created
SMOKE_KEEP=1 ./infrastructure/scripts/smoke_prod.sh # keep the stack for the e2e and load tests
```

It uses compose project `sv-smoke`, `.env.smoke`, `deploy/smoke-certs/` and ports 18080/18443, so it cannot disturb a real deployment
or the development stack. The run takes roughly 3 minutes once images are cached.

## Browser end-to-end

With a stack running (for example `SMOKE_KEEP=1`), create an administrator and run:

```bash
docker compose -p sv-smoke --env-file .env.smoke -f docker-compose.prod.yml exec -T -e SV_BOOTSTRAP_PASSWORD backend \
  python manage.py bootstrap_org --org-name "E2E" --org-slug e2e --email e2e.admin@example.test --full-name "E2E Admin"
cd e2e && npm ci
E2E_BASE_URL=https://localhost:18443 E2E_ADMIN_EMAIL=e2e.admin@example.test E2E_ADMIN_PASSWORD=... npm test
```

The test drives the installed Edge or Chrome (`E2E_BROWSER` to override) with `playwright-core`, so no browser is downloaded. It fails on any
console error or CSP violation.

`npm run test:layout` (same variables; works against the Vite dev server at `http://localhost:5173` too) checks the app shell in a real
browser: the window never scrolls, the sidebar does not move when the page scrolls, the navigation scrolls by itself in a short window,
the phone drawer scrolls by itself, a new page starts at the top, nothing overflows sideways, and the page and sidebar scrollbars are hidden (the test browser runs with real scrollbars enabled) while the wheel, keyboard, Tab focus and touch drags still scroll. Set `E2E_SHOTS=dir` to save screenshots.

`npm run test:actions` checks the action hierarchy in a real browser (secondary buttons, the Chart/Table control, the file picker with its
focus ring and validation, the template download, navigation, and the phone layout). Set `E2E_STATE=file` so repeated runs reuse one signed-in
browser instead of registering a new device each time.

## Load-test scenarios and method

The master requirements ask for documented scenarios and measured response times and resource use *before* claiming scalability.
The scenarios, all in `infrastructure/loadtest/run.mjs`:

| Scenario | What it does | What to read from it |
|---|---|---|
| **Concurrent users** (`browse`) | 20 virtual users, each repeatedly loading `me`, the dashboard, the credential list, unread notifications and devices, with 100-400 ms think time, for 30 s | Latency percentiles per endpoint and total throughput; errors |
| **Credential reveals** (`reveal`) | Each user reveals its own credentials at ~26/minute (just under the 30/minute limit); then one user fires 40 in a row | Reveal latency (decrypt + audit write + advisory lock); the throttle answering 429 after 30 |
| **Audit queries** (`audit`) | An administrator pages and filters the audit log, requests the JSON report, exports CSV and verifies the whole hash chain | Query latency at the audit volume produced by the earlier scenarios |
| **Imports** (`import`) | Uploads a 150-row workbook (processed inside the request) and a 1,000-row one (queued for the worker) | Request latency; worker throughput; time to completion |
| **Lockdown propagation** | `measure_lockdown_latency.mjs`: an administrator activates a lockdown while an employee is connected over WebSocket; 15 rounds | Time from the administrator's request to the employee's socket receiving the event |

How to run (against the smoke stack kept alive with `SMOKE_KEEP=1`):

```bash
# 1. seed 20 users x 10 credentials and pre-authenticated sessions (test stacks only; audit records cannot be deleted afterwards)
docker compose -p sv-smoke --env-file .env.smoke -f docker-compose.prod.yml exec -T -e LOAD_USERS=20 -e LOAD_CREDENTIALS=10 \
  backend python manage.py shell < infrastructure/loadtest/seed.py > seed.json
# 2. workbooks
python infrastructure/loadtest/make_xlsx.py 150 small.xlsx small ; python infrastructure/loadtest/make_xlsx.py 1000 large.xlsx large
# 3. run from a container on the stack's network (direct to the backend; through nginx the edge rate limit would be measured instead)
docker run --rm --network sv-smoke_edge -v "$PWD/infrastructure/loadtest:/lt:ro" -v "$PWD:/data" node:22-alpine \
  node /lt/run.mjs --seed /data/seed.json --target http://backend:8000 --origin https://localhost:18443 \
  --import-small /data/small.xlsx --import-large /data/large.xlsx --out /data/load-result.json
```

(The stack needs `backend` in `DJANGO_ALLOWED_HOSTS` for step 3.) Resource use was sampled with `docker stats --no-stream` every 2 s
during the run.

**Caveats that apply to every number in the report:** one laptop running the load generator, Docker Desktop, the database and
all services together; a single backend process limited to one CPU; synthetic users; no network latency. They show relative
behavior and the shape of the limits; they are not capacity forecasts.

## Query-plan review

```bash
docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" sv_explain'
cd backend && POSTGRES_DB=sv_explain python manage.py migrate
POSTGRES_DB=sv_explain python -c "import os,django;os.environ['DJANGO_SETTINGS_MODULE']='config.settings';django.setup();exec(open('../infrastructure/scripts/explain_hot_queries.py',encoding='utf-8').read())"
docker compose exec db sh -c 'dropdb -U "$POSTGRES_USER" sv_explain'
```

The script refuses to run against any database whose name does not start with `sv_explain`.

## Tests that cannot pass yet

See [known-limitations.md](known-limitations.md): there is no test against a real SMTP server, a real certificate authority, a KMS,
multiple backend replicas, or a browser other than Chromium-based ones; the frontend suite runs against a mocked API.
