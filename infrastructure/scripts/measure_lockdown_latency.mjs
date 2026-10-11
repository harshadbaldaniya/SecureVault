// End-to-end lockdown propagation: admin POST /lockdown/activate/ -> Daphne -> PostgreSQL commit
// -> Redis channel layer -> a separately connected employee WebSocket.
//
// DEVELOPMENT/TEST STACKS ONLY: it repeatedly locks down and restores the dedicated "latency-test" org.
// 1) Create the org and its two users (any strong password, used for both):
//      bash:  PW='<password>' docker compose exec -T -e PW backend python manage.py shell < infrastructure/scripts/make_latency_org.py
// 2) Measure (Node 22+; rounds are paced at one per 7 s to respect the sign-in throttle):
//      node infrastructure/scripts/measure_lockdown_latency.mjs '<password>' 15
// The figure includes the admin's HTTP request, password re-authentication, the DB commit, Redis fan-out
// and WebSocket delivery: an upper bound for "time until connected clients are told".
// Defaults target the development stack. For the production stack through nginx:
//   SV_BASE=https://localhost:18443 SV_WS=wss://localhost:18443/ws/events/ SV_ORIGIN=https://localhost:18443 \n//   NODE_TLS_REJECT_UNAUTHORIZED=0 node ... (the last one only because the test certificate is self-signed)
const BASE = process.env.SV_BASE ?? "http://127.0.0.1:8000";
const WS_URL = process.env.SV_WS ?? "ws://127.0.0.1:8000/ws/events/";
const ORIGIN = process.env.SV_ORIGIN ?? "http://localhost";
const [password, roundsArg] = process.argv.slice(2);
const rounds = Number(roundsArg ?? 20);

function cookies(response) {
  const jar = {};
  for (const line of response.headers.getSetCookie()) {
    const [pair] = line.split(";");
    const [name, ...rest] = pair.split("=");
    jar[name.trim()] = rest.join("=");
  }
  return jar;
}

async function login(email) {
  const first = await fetch(`${BASE}/api/v1/auth/csrf/`);
  const csrf = cookies(first).sv_csrftoken;
  const res = await fetch(`${BASE}/api/v1/auth/login/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, Cookie: `sv_csrftoken=${csrf}`, Origin: ORIGIN },
    body: JSON.stringify({ email, password }),
  });
  if (res.status !== 200) throw new Error(`login ${email} -> ${res.status} ${await res.text()}`);
  const jar = cookies(res);
  return { session: jar.sv_session, csrf: jar.sv_csrftoken ?? csrf };
}

async function post(auth, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": auth.csrf,
      Origin: ORIGIN,
      Cookie: `sv_session=${auth.session}; sv_csrftoken=${auth.csrf}`,
    },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json().catch(() => null) };
}

function openSocket(session) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(WS_URL, { headers: { Cookie: `sv_session=${session}`, Origin: ORIGIN } });
    const timer = setTimeout(() => reject(new Error("socket hello timeout")), 5000);
    ws.addEventListener("message", function onHello(event) {
      const msg = JSON.parse(event.data);
      if (msg.type === "hello") {
        clearTimeout(timer);
        ws.removeEventListener("message", onHello);
        resolve(ws);
      }
    });
    ws.addEventListener("error", (e) => reject(new Error(`socket error ${e.message ?? ""}`)));
  });
}

const samples = [];
const admin = await login("sec@latency.test");
for (let i = 0; i < rounds; i++) {
  const employee = await login("emp@latency.test");
  const ws = await openSocket(employee.session);
  const received = new Promise((resolve) => {
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "lockdown.activated") resolve(performance.now());
    });
  });
  const closed = new Promise((resolve) => ws.addEventListener("close", (e) => resolve(e.code)));

  const sent = performance.now();
  const activated = await post(admin, "/api/v1/lockdown/activate/", {
    scope: "GLOBAL", reason: `Latency measurement round ${i + 1}`, password,
  });
  if (activated.status !== 201) throw new Error(`activate -> ${activated.status} ${JSON.stringify(activated.body)}`);
  const arrived = await received;
  const closeCode = await closed;
  samples.push(arrived - sent);

  const resolved = await post(admin, `/api/v1/lockdown/${activated.body.id}/resolve/`, { note: "measurement", password });
  if (resolved.status !== 200) throw new Error(`resolve -> ${resolved.status}`);
  if (i === 0) console.log(`round 1: socket closed with code ${closeCode}`);
  await new Promise((r) => setTimeout(r, 7000)); // stay under the 10 sign-ins/minute throttle
}

samples.sort((a, b) => a - b);
const pct = (p) => samples[Math.min(samples.length - 1, Math.ceil((p / 100) * samples.length) - 1)];
console.log(`rounds=${samples.length}  min=${samples[0].toFixed(1)}ms  p50=${pct(50).toFixed(1)}ms  p95=${pct(95).toFixed(1)}ms  max=${samples.at(-1).toFixed(1)}ms`);
console.log(`under 1 s: ${samples.filter((s) => s < 1000).length}/${samples.length}`);
