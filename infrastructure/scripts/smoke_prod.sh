#!/usr/bin/env bash
# Builds and starts the PRODUCTION stack with throwaway secrets, then checks what the deployment promises:
# TLS and security headers at the edge, which services are reachable, the three database roles, the
# sign-in -> vault -> reveal -> lockdown flow through nginx, WebSocket handshakes, container hardening, and that the
# logs contain no secrets. It uses its own compose project (sv-smoke), env file, certificate and ports, so it never
# touches a real deployment or the development stack, and it removes everything it created when it finishes.
#
#   ./infrastructure/scripts/smoke_prod.sh                  # run, then tear down
#   SMOKE_KEEP=1 ./infrastructure/scripts/smoke_prod.sh     # leave the stack running for inspection
#
# Requires docker compose, openssl, curl and Node 22+. The exit status is the number of failed checks.
set -uo pipefail

cd "$(dirname "$0")/../.."
PROJECT=sv-smoke
ENV_FILE=.env.smoke
CERT_DIR=deploy/smoke-certs
HTTP_PORT="${SMOKE_HTTP_PORT:-18080}"
HTTPS_PORT="${SMOKE_HTTPS_PORT:-18443}"
BASE="https://localhost:${HTTPS_PORT}"
compose=(docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f docker-compose.prod.yml)

# ------------------------------------------------------------------------------------------------ test helpers
pass=0
fail=0
ok() { printf '  PASS  %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }
t() { # t "description" predicate args...   (predicate is any command; success = pass)
  local what="$1"
  shift
  if "$@"; then ok "$what"; else bad "$what"; fi
}
section() { printf '\n== %s\n' "$1"; }
has() { grep -qiE -- "$1" <<<"$2"; }  # has REGEX TEXT (case-insensitive)
hasf() { grep -qF -- "$1" <<<"$2"; }  # hasf LITERAL TEXT
not() { ! "$@"; }
eq() { [ "$1" = "$2" ]; }

rand() { openssl rand -base64 64 | tr '+/' '-_' | tr -d '=\n' | cut -c1-"${1:-40}"; }
key() { printf '1:%s' "$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"; }
# --resolve pins localhost to IPv4: on Windows with Docker Desktop, trying ::1 first stalls.
http() { curl -sk --max-time 30 --resolve "localhost:${HTTPS_PORT}:127.0.0.1" "$@"; }
code() { http -o /dev/null -w '%{http_code}' "$@"; }
dx() { "${compose[@]}" exec -T "$@"; }
jar="$(mktemp)"

cleanup() {
  rm -f "$jar"
  if [ -z "${SMOKE_KEEP:-}" ]; then
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1
    rm -rf "$ENV_FILE" "$CERT_DIR"
  else
    echo "SMOKE_KEEP set: stack '$PROJECT' left running on $BASE (env file $ENV_FILE)."
  fi
}
trap cleanup EXIT

# ------------------------------------------------------------------------------------------------ start
section "Starting the stack with generated secrets"
SUPER_PW="$(rand 32)"
OWNER_PW="$(rand 32)"
APP_PW="$(rand 32)"
REDIS_PW="$(rand 32)"
METRICS_TOKEN="$(rand 40)"
ADMIN_PW="$(rand 28)"
SECRET="Sm0ke!$(rand 20)"
SEARCH_TERM="needle-$(rand 12)"
cat >"$ENV_FILE" <<EOF
DJANGO_ALLOWED_HOSTS=localhost
DJANGO_CSRF_TRUSTED_ORIGINS=${BASE}
FRONTEND_URL=${BASE}
SV_HTTP_PORT=${HTTP_PORT}
SV_HTTPS_PORT=${HTTPS_PORT}
SV_CERT_DIR=./${CERT_DIR}
DJANGO_SECRET_KEY=$(rand 80)
POSTGRES_DB=securevault
POSTGRES_USER=postgres_admin
POSTGRES_PASSWORD=${SUPER_PW}
SV_OWNER_DB_USER=securevault_owner
SV_OWNER_DB_PASSWORD=${OWNER_PW}
SV_APP_DB_USER=securevault_app
SV_APP_DB_PASSWORD=${APP_PW}
REDIS_PASSWORD=${REDIS_PW}
SV_MFA_ENCRYPTION_KEYS=$(key)
SV_VAULT_KEK_KEYS=$(key)
SV_BLIND_INDEX_KEYS=$(key)
SV_METRICS_TOKEN=${METRICS_TOKEN}
DJANGO_EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend
EOF
CERT_DIR="$CERT_DIR" FORCE=1 ./infrastructure/scripts/make_dev_cert.sh localhost >/dev/null 2>&1 || { echo "could not create the test certificate"; exit 1; }

if "${compose[@]}" up -d --build --wait --wait-timeout 420; then
  ok "the stack builds, migrates and every service becomes healthy"
else
  bad "the stack builds, migrates and every service becomes healthy"
  "${compose[@]}" ps -a
  "${compose[@]}" logs --tail 40 migrate backend
  exit 1
fi

# ------------------------------------------------------------------------------------------------ edge
section "Edge: TLS, redirects, headers"
redirect="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 --resolve "localhost:${HTTP_PORT}:127.0.0.1" "http://localhost:${HTTP_PORT}/x")"
t "plain HTTP redirects to HTTPS" has '^301 https://localhost' "$redirect"
tls() { echo | openssl s_client -connect "127.0.0.1:${HTTPS_PORT}" -servername localhost "$1" 2>&1; }
t "TLS 1.2 is accepted" has 'Protocol *: TLSv1.2' "$(tls -tls1_2)"
t "TLS 1.3 is accepted" has 'Protocol *: TLSv1.3' "$(tls -tls1_3)"

index_headers="$(http -sI "$BASE/" | tr -d '\r')"
t "HSTS is set" has '^strict-transport-security: max-age=31536000' "$index_headers"
t "CSP restricts everything to this origin" has "^content-security-policy: default-src 'self'" "$index_headers"
t "CSP forbids framing" has "frame-ancestors 'none'" "$index_headers"
t "CSP has no unsafe-inline or unsafe-eval" not has "unsafe-(inline|eval)" "$index_headers"
t "X-Content-Type-Options: nosniff" has '^x-content-type-options: nosniff' "$index_headers"
t "X-Frame-Options: DENY" has '^x-frame-options: deny' "$index_headers"
t "Referrer-Policy is set" has '^referrer-policy: same-origin' "$index_headers"
t "Permissions-Policy is set" has '^permissions-policy:' "$index_headers"
t "index.html is not cached" has '^cache-control: no-cache' "$index_headers"
t "the server does not announce its version" not has '^server: nginx/' "$index_headers"
asset="$(http "$BASE/" | grep -o '/assets/[A-Za-z0-9._-]*\.js' | head -1)"
t "hashed assets are cached as immutable" has '^cache-control: public, max-age=31536000, immutable' "$(http -sI "$BASE$asset" | tr -d '\r')"
t "unknown paths fall back to the single-page app" hasf '<div id="root">' "$(http "$BASE/some/client/route")"
t "dot-files are not served" eq "$(code "$BASE/.env")" 403

# ------------------------------------------------------------------------------------------------ API surface
section "API surface through nginx"
health="$(http -si "$BASE/api/v1/health/" | tr -d '\r')"
t "the health endpoint answers ok" has '"status": *"ok"' "$health"
t "API responses are never cached" has '^cache-control: no-store' "$health"
t "API responses carry a request id" has '^x-request-id:' "$health"
t "metrics are not reachable from the internet" eq "$(code "$BASE/api/v1/metrics/")" 404
t "API docs are off by default (docs)" eq "$(code "$BASE/api/v1/docs/")" 404
t "API docs are off by default (schema)" eq "$(code "$BASE/api/v1/schema/")" 404
t "anonymous API requests get 401" eq "$(code "$BASE/api/v1/auth/me/")" 401
t "login without a CSRF token is refused" eq "$(code -X POST -H "Origin: $BASE" -H 'Content-Type: application/json' -d '{}' "$BASE/api/v1/auth/login/")" 403

# ------------------------------------------------------------------------------------------------ session
section "Bootstrap, sign-in and cookies"
if dx -e SV_BOOTSTRAP_PASSWORD="$ADMIN_PW" backend python manage.py bootstrap_org \
  --org-name "Smoke Org" --org-slug smoke --email admin@smoke.test --full-name "Smoke Admin" >/dev/null 2>&1; then
  ok "bootstrap_org creates the first administrator (running as the restricted database role)"
else
  bad "bootstrap_org creates the first administrator (running as the restricted database role)"
fi

http -c "$jar" -o /dev/null "$BASE/api/v1/auth/csrf/"
csrf="$(awk '$6=="sv_csrftoken"{print $7}' "$jar")"
login="$(http -b "$jar" -c "$jar" -i -X POST "$BASE/api/v1/auth/login/" -H "X-CSRFToken: $csrf" -H "Origin: $BASE" \
  -H 'Content-Type: application/json' -d "{\"email\":\"admin@smoke.test\",\"password\":\"${ADMIN_PW}\"}" | tr -d '\r')"
t "sign-in succeeds" has '^HTTP/[0-9.]+ 200' "$login"
session_cookie="$(grep -i '^set-cookie: sv_session=' <<<"$login")"
t "the session cookie is HttpOnly" has 'httponly' "$session_cookie"
t "the session cookie is Secure" has '; secure' "$session_cookie"
t "the session cookie is SameSite=Strict" has 'samesite=strict' "$session_cookie"
session="$(awk '$6=="sv_session"{print $7}' "$jar")"
csrf="$(awk '$6=="sv_csrftoken"{print $7}' "$jar")"
t "the session identifies the administrator" hasf ORG_ADMIN "$(http -b "$jar" "$BASE/api/v1/auth/me/")"

api() { # api METHOD PATH [json-body]   -> response body
  local method="$1" path="$2"
  if [ $# -ge 3 ]; then
    http -b "$jar" -c "$jar" -X "$method" "$BASE$path" -H "X-CSRFToken: $csrf" -H "Origin: $BASE" -H 'Content-Type: application/json' -d "$3"
  else
    http -b "$jar" -c "$jar" -X "$method" "$BASE$path" -H "X-CSRFToken: $csrf" -H "Origin: $BASE"
  fi
}
api_code() { # api_code METHOD PATH json-body   -> status code only
  http -b "$jar" -c "$jar" -o /dev/null -w '%{http_code}' -X "$1" "$BASE$2" -H "X-CSRFToken: $csrf" -H "Origin: $BASE" -H 'Content-Type: application/json' -d "$3"
}
id_of() { grep -o '"id": *"[^"]*"' <<<"$1" | head -1 | sed 's/.*"\([^"]*\)"$/\1/'; }

# ------------------------------------------------------------------------------------------------ vault
section "Vault: store, reveal, audit, lockdown"
created="$(api POST /api/v1/vault/credentials/ "{\"title\":\"Smoke DB\",\"username\":\"svc\",\"password\":\"${SECRET}\"}")"
cred_id="$(id_of "$created")"
t "a credential is created" test -n "$cred_id"
t "the create response does not contain the secret" not hasf "$SECRET" "$created"
t "the credential list does not contain the secret" not hasf "$SECRET" "$(api GET '/api/v1/vault/credentials/')"
reveal="$(http -b "$jar" -c "$jar" -si -X POST "$BASE/api/v1/vault/credentials/$cred_id/reveal/" -H "X-CSRFToken: $csrf" \
  -H "Origin: $BASE" -H 'Content-Type: application/json' -d '{"purpose":"view"}' | tr -d '\r')"
t "reveal returns the secret" hasf "$SECRET" "$reveal"
t "reveal responses are not cacheable" has '^cache-control: no-store' "$reveal"
audit="$(api GET '/api/v1/audit-logs/?action=REVEAL')"
t "the reveal is in the audit log" has '"action": *"REVEAL"' "$audit"
t "the audit log does not contain the secret" not hasf "$SECRET" "$audit"
t "the audit hash chain verifies" has '"valid": *true' "$(api GET /api/v1/audit-logs/verify/)"
api GET "/api/v1/vault/credentials/?search=${SEARCH_TERM}" >/dev/null # for the log-hygiene check below

lock="$(api POST /api/v1/lockdown/activate/ "{\"scope\":\"GLOBAL\",\"reason\":\"Smoke test of emergency lockdown\",\"password\":\"${ADMIN_PW}\"}")"
t "an emergency lockdown can be activated" has '"scope": *"GLOBAL"' "$lock"
t "reveal is refused with 423 during a lockdown, even for the administrator" eq "$(api_code POST "/api/v1/vault/credentials/$cred_id/reveal/" '{"purpose":"view"}')" 423
api POST "/api/v1/lockdown/$(id_of "$lock")/resolve/" "{\"note\":\"Smoke test finished\",\"password\":\"${ADMIN_PW}\"}" >/dev/null
t "reveal works again once the lockdown is resolved" eq "$(api_code POST "/api/v1/vault/credentials/$cred_id/reveal/" '{"purpose":"view"}')" 200

# ------------------------------------------------------------------------------------------------ websocket
section "WebSocket through nginx"
if NODE_TLS_REJECT_UNAUTHORIZED=0 node infrastructure/scripts/smoke_ws.mjs "wss://127.0.0.1:${HTTPS_PORT}/ws/events/" "$BASE" "$session"; then
  ok "WebSocket handshake rules hold (anonymous, authenticated, foreign origin)"
else
  bad "WebSocket handshake rules hold (anonymous, authenticated, foreign origin)"
fi

# ------------------------------------------------------------------------------------------------ database roles
section "Database roles"
psql_as() { dx -e PGPASSWORD="$2" db psql -h 127.0.0.1 -U "$1" -d securevault -tAc "$3" 2>&1; }
t "the application role can read the audit trail" eq "$(psql_as securevault_app "$APP_PW" 'SELECT count(*) > 0 FROM audit_auditlog')" t
for statement in "DELETE FROM audit_auditlog" "UPDATE audit_auditlog SET reason = 'x'" "TRUNCATE audit_auditlog" \
  "DROP TABLE audit_auditlog" "CREATE TABLE rogue (id int)" "DELETE FROM django_migrations"; do
  t "the application role is refused: $statement" has 'permission denied|must be owner' "$(psql_as securevault_app "$APP_PW" "$statement")"
done
t "the owner role is not a superuser" eq "$(psql_as securevault_owner "$OWNER_PW" 'SELECT rolsuper FROM pg_roles WHERE rolname = current_user')" f
t "the audit hash chain still verifies after those attempts" has '"valid": *true' "$(api GET /api/v1/audit-logs/verify/)"

# ------------------------------------------------------------------------------------------------ isolation + hardening
section "Isolation and container hardening"
for service in backend worker web redis; do
  environment="$(dx "$service" env 2>/dev/null)"
  t "$service does not hold the database superuser password" not hasf "$SUPER_PW" "$environment"
  t "$service does not hold the database owner password" not hasf "$OWNER_PW" "$environment"
done
for service in db redis backend worker; do
  t "$service publishes no host ports" test -z "$(docker port "$("${compose[@]}" ps -q "$service")")"
done
for service in backend worker web redis migrate; do
  info="$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.CapDrop}}|{{.HostConfig.SecurityOpt}}' "$("${compose[@]}" ps -aq "$service")")"
  t "$service: read-only filesystem, no capabilities, no privilege escalation" has '^true\|.*ALL.*\|.*no-new-privileges' "$info"
done
t "the worker reports healthy" eq "$(docker inspect --format '{{.State.Health.Status}}' "$("${compose[@]}" ps -q worker)")" healthy
t "the backend does not run as root" not eq "$(dx backend id -u | tr -d '\r')" 0
t "the web container does not run as root" not eq "$(dx web id -u | tr -d '\r')" 0
for round in 1 2 3; do # bursts of concurrent requests: connection use must stay within the pools, not grow per request
  for _ in $(seq 1 15); do http -o /dev/null -b "$jar" "$BASE/api/v1/auth/me/" & done
  wait
done
app_connections="$(psql_as securevault_owner "$OWNER_PW" "SELECT count(*) FROM pg_stat_activity WHERE usename = 'securevault_app'")"
t "database connections stay within the pools after 45 concurrent requests (found ${app_connections}, limit 20)" test "$app_connections" -le 20

# ------------------------------------------------------------------------------------------------ metrics
section "Metrics (internal network only)"
SCRAPE='
import os, urllib.request as u, urllib.error as e
headers = {"Host": "localhost"}
if os.environ.get("AUTH"):
    headers["Authorization"] = os.environ["AUTH"]
try:
    r = u.urlopen(u.Request("http://127.0.0.1:8000/api/v1/metrics/", headers=headers), timeout=5)
    print(r.status); print(r.read().decode())
except e.HTTPError as x:
    print(x.code)
'
scrape() { dx -e AUTH="$1" backend python -c "$SCRAPE" | tr -d '\r'; }
with_token="$(scrape "Bearer ${METRICS_TOKEN}")"
t "a scraper with the token receives aggregate metrics" has 'sv_users\{status="ACTIVE"\} 1' "$with_token"
t "a scrape without the token is refused" eq "$(scrape '' | head -1)" 401
t "metrics contain no people, organizations or credential names" not has 'admin@smoke|Smoke Org|Smoke DB' "$with_token"

# ------------------------------------------------------------------------------------------------ logs
section "Logs"
logs="$("${compose[@]}" logs --no-color backend worker web db redis 2>&1)"
t "backend logs are structured JSON with route and status" has '"route":' "$logs"
for secret_name in SECRET ADMIN_PW APP_PW OWNER_PW SUPER_PW REDIS_PW METRICS_TOKEN; do
  t "logs do not contain the ${secret_name}" not hasf "${!secret_name}" "$logs"
done
t "logs do not contain the session cookie value" not hasf "$session" "$logs"
t "logs do not contain the CSRF token" not hasf "$csrf" "$logs"
t "logs do not contain query strings (search terms)" not hasf "$SEARCH_TERM" "$logs"

# ------------------------------------------------------------------------------------------------ summary
printf '\n%d passed, %d failed\n' "$pass" "$fail"
exit "$fail"
