# Setup guide (development)

For running SecureVault on your own machine to develop or evaluate it. For a production-style deployment see
[deployment-guide.md](deployment-guide.md).

## What you need

| Tool | Version used | Notes |
|---|---|---|
| Docker with Compose v2 | Docker 29 / Compose 5 | PostgreSQL, Redis and the backend run in containers |
| Node.js | 22 | frontend dev server and tests |
| Python | 3.13 | only to run the backend tests and tools on your machine (the backend itself runs in Docker) |
| Git | any recent | |

Commands below are for **PowerShell** on Windows; the macOS/Linux equivalents are noted where they differ.

## 1. Get the code and create your private configuration

```powershell
git clone https://github.com/harshadbaldaniya/SecureVault.git
cd SecureVault
py infrastructure/scripts/init_env.py        # macOS/Linux: python3 infrastructure/scripts/init_env.py
```

`init_env.py` writes `.env` from `.env.example` with fresh random secrets and encryption keys. It never prints them and
refuses to overwrite an existing file. `.env` is git-ignored; **never commit it**. Losing the keys in `.env` makes the
credentials you store with them unreadable, so back it up if the data matters.

> If you already have a PostgreSQL or Redis on port 5432/6379/8000, set `SV_DB_PORT`, `SV_REDIS_PORT` or `SV_API_PORT` in
> `.env` before the next step (and use `127.0.0.1`, not `localhost`, for `POSTGRES_HOST`/`REDIS_URL` on Windows; the
> `.env.example` default already does).

## 2. Start the backend, database and Redis

```powershell
docker compose up -d --build --wait
```

This builds the backend image, applies the database migrations and waits until everything is healthy. Check:

```powershell
curl.exe http://127.0.0.1:8000/api/v1/health/        # {"status":"ok", ...}
```

The interactive API documentation is at <http://127.0.0.1:8000/api/v1/docs/> (sign in first; it is enabled in development).

## 3. Create the first administrator

There is deliberately no default account. Choose a strong password (at least 12 characters):

```powershell
$env:SV_BOOTSTRAP_PASSWORD = Read-Host "Admin password"        # bash: read -s SV_BOOTSTRAP_PASSWORD; export SV_BOOTSTRAP_PASSWORD
docker compose exec -T -e SV_BOOTSTRAP_PASSWORD backend python manage.py bootstrap_org `
    --org-name "My Company" --org-slug my-company --email you@example.com --full-name "Your Name"
Remove-Item Env:SV_BOOTSTRAP_PASSWORD
```

## 4. Start the frontend

```powershell
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173> and sign in with the account you just created. The dev server proxies `/api` and `/ws` to the
backend on port 8000. Invitation and password-reset emails are written as files to `backend/var/mail` inside the backend
container in development (`docker compose exec backend ls var/mail`) instead of being sent.

## 5. Run the tests

Backend (needs the database and Redis containers from step 2):

```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1                       # macOS/Linux: source venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                          # about 2-4 minutes, 400+ tests
ruff check . ; ruff format --check .
```

Frontend:

```powershell
cd frontend
npm test                # unit/component tests
npm run typecheck
npm run build
```

Production-stack checks (smoke test, browser end-to-end, load test) are described in [testing-guide.md](testing-guide.md).

## Everyday commands

| Task | Command |
|---|---|
| Stop everything (keeps data) | `docker compose stop` |
| Start again | `docker compose start` |
| Rebuild after pulling changes | `docker compose up -d --build --wait` (applies new migrations) |
| Backend logs | `docker compose logs -f backend` |
| Open a Django shell | `docker compose exec backend python manage.py shell` |
| Verify the audit chain | `docker compose exec backend python manage.py verify_audit_chain` |
| **Delete all development data** | `docker compose down -v` (destroys the database volume; only when you mean it) |

## Troubleshooting

- **Slow requests or tests on Windows (several seconds per new connection):** use `127.0.0.1`, not `localhost`, in `.env`.
- **`address already in use`:** change the host ports as described in step 1.
- **The backend container is "unhealthy":** `docker compose logs backend`; a missing or malformed key in `.env` is reported
  at startup ("Environment variable ... is required", or "must not share key material").
- **Login says "Invalid email or password" for the account you created:** the password was rejected by a validator when you
  created it (the command would have said so), or you are using a different `.env`/database than the one you bootstrapped.
- **Too many failed sign-ins:** an email is locked for 15 minutes after 5 failures.
