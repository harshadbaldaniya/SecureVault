// Load scenarios for a running SecureVault stack (Node 22+, no dependencies).
//
// Run it from a container on the stack's network so it talks to the backend directly. (Through nginx, the edge rate
// limit of 30 requests/second per client address would be what you measure.) See docs/testing-guide.md.
//
//   node run.mjs --seed seed.json --target http://backend:8000 --origin https://localhost:18443 \
//        --duration 30 --out result.json [--import-small small.xlsx --import-large large.xlsx]
//
// Scenarios, run one after another:
//   browse   N virtual users repeatedly load the pages a person sees after signing in (me, dashboard, credential
//            list, unread notifications, devices), with 100-400 ms think time
//   reveal   each user reveals its own credentials at just under the per-user limit (30/minute); then one user
//            exceeds the limit to show the throttle answering 429 instead of the server absorbing the burst
//   audit    an administrator pages and filters the audit log, exports it, and verifies the hash chain
//   import   an administrator uploads a small workbook (processed inside the request) and a large one (queued for the
//            background worker), and waits for the large one to finish
//
// Latencies are measured by the client from request start to the full response body. They include this container's
// own CPU, so treat them as an upper bound on server time on the machine you ran this on.
import { readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";

const { values: args } = parseArgs({
  options: {
    seed: { type: "string" },
    target: { type: "string", default: "http://backend:8000" },
    origin: { type: "string", default: "https://localhost:18443" },
    host: { type: "string", default: "localhost" },
    duration: { type: "string", default: "30" },
    out: { type: "string", default: "result.json" },
    scenarios: { type: "string", default: "browse,reveal,audit,import" },
    "import-small": { type: "string" },
    "import-large": { type: "string" },
  },
});
// manage.py shell prints a banner before the script output, so the JSON is the last line.
const seedLines = readFileSync(args.seed, "utf8").trim().split(String.fromCharCode(10));
const seed = JSON.parse(seedLines.at(-1));
const duration = Number(args.duration) * 1000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const between = (low, high) => low + Math.random() * (high - low);

// --------------------------------------------------------------------------- measurement
const samples = new Map(); // label -> {latencies: number[], statuses: Map<number, number>}
function record(label, status, ms) {
  if (!samples.has(label)) samples.set(label, { latencies: [], statuses: new Map() });
  const entry = samples.get(label);
  entry.latencies.push(ms);
  entry.statuses.set(status, (entry.statuses.get(status) ?? 0) + 1);
}

function percentile(sorted, p) {
  if (sorted.length === 0) return 0;
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}

function summarize(wallSeconds) {
  const rows = [];
  for (const [label, { latencies, statuses }] of samples) {
    const sorted = [...latencies].sort((a, b) => a - b);
    rows.push({
      label,
      requests: sorted.length,
      perSecond: +(sorted.length / wallSeconds).toFixed(1),
      p50: Math.round(percentile(sorted, 50)),
      p95: Math.round(percentile(sorted, 95)),
      p99: Math.round(percentile(sorted, 99)),
      max: Math.round(sorted.at(-1) ?? 0),
      statuses: Object.fromEntries([...statuses].sort()),
    });
  }
  return rows;
}

// --------------------------------------------------------------------------- HTTP
// Django accepts a 32-character alphanumeric CSRF secret in the cookie with the same value in the header.
const csrfToken = "LoadTestCsrfSecret0123456789abcd";
function baseHeaders(user, clientIp) {
  return {
    Host: args.host,
    Origin: args.origin,
    "X-Forwarded-Proto": "https",
    "X-Forwarded-For": clientIp, // the backend trusts exactly one proxy hop; each virtual user gets its own address
    "X-CSRFToken": csrfToken,
    Cookie: `sv_session=${user.session}; sv_csrftoken=${csrfToken}`,
    Accept: "application/json",
  };
}

async function call(user, label, method, path, { body, form, clientIp } = {}) {
  const headers = baseHeaders(user, clientIp ?? user.ip);
  let payload;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  } else if (form) {
    payload = form; // multipart: fetch sets the boundary
  }
  const started = performance.now();
  let status = 0;
  let text = "";
  try {
    const response = await fetch(`${args.target}${path}`, { method, headers, body: payload });
    status = response.status;
    text = await response.text();
  } catch (error) {
    status = 0;
    text = String(error);
  }
  record(label, status, performance.now() - started);
  return { status, text };
}

const users = seed.users.map((user, index) => ({ ...user, ip: `10.20.${Math.floor(index / 250)}.${(index % 250) + 1}` }));
const admin = { ...seed.admin, ip: "10.20.250.250" };

// --------------------------------------------------------------------------- scenarios
async function browse() {
  const until = Date.now() + duration;
  await Promise.all(
    users.map(async (user) => {
      while (Date.now() < until) {
        await call(user, "GET /auth/me/", "GET", "/api/v1/auth/me/");
        await call(user, "GET /dashboard/", "GET", "/api/v1/dashboard/");
        await call(user, "GET /vault/credentials/", "GET", "/api/v1/vault/credentials/");
        await call(user, "GET /notifications/unread-count/", "GET", "/api/v1/notifications/unread-count/");
        await call(user, "GET /devices/", "GET", "/api/v1/devices/");
        await sleep(between(100, 400));
      }
    }),
  );
}

async function reveal() {
  const until = Date.now() + duration;
  await Promise.all(
    users.map(async (user, index) => {
      await sleep(between(0, 2000)); // spread the users out
      let next = 0;
      while (Date.now() < until) {
        const id = user.credentials[next++ % user.credentials.length];
        await call(user, "POST /vault/credentials/{id}/reveal/", "POST", `/api/v1/vault/credentials/${id}/reveal/`, { body: { purpose: "view" } });
        await sleep(2300); // ~26 per minute: just under the 30/minute per-user limit
      }
      return index;
    }),
  );
  // Over the limit: the 31st reveal inside a minute must be answered 429 quickly rather than absorbed.
  const abuser = users[0];
  await sleep(61000); // let this user's window empty first
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await call(abuser, "POST reveal (burst of 40 by one user)", "POST", `/api/v1/vault/credentials/${abuser.credentials[0]}/reveal/`, { body: { purpose: "view" } });
  }
}

async function audit() {
  const rounds = 20;
  for (let round = 0; round < rounds; round += 1) {
    await call(admin, "GET /audit-logs/ (page 1)", "GET", "/api/v1/audit-logs/");
    await call(admin, "GET /audit-logs/?action=REVEAL", "GET", "/api/v1/audit-logs/?action=REVEAL");
    await call(admin, "GET /audit-logs/?search=user00", "GET", "/api/v1/audit-logs/?search=user00");
    await call(admin, "GET /audit-logs/?page=5", "GET", "/api/v1/audit-logs/?page=5");
    await call(admin, "GET /reports/audit/ (JSON page)", "GET", "/api/v1/reports/audit/?page_size=50");
  }
  for (let round = 0; round < 3; round += 1) {
    await call(admin, "GET /reports/audit/?format=csv (export)", "GET", "/api/v1/reports/audit/?format=csv");
    await call(admin, "GET /audit-logs/verify/ (full chain)", "GET", "/api/v1/audit-logs/verify/");
  }
}

async function importFile(path, label) {
  const bytes = readFileSync(path);
  const form = new FormData();
  form.append("file", new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), "load.xlsx");
  const { status, text } = await call(admin, label, "POST", "/api/v1/imports/", { form });
  const job = status === 201 ? JSON.parse(text) : null;
  return job;
}

async function imports() {
  if (args["import-small"]) {
    const job = await importFile(args["import-small"], "POST /imports/ (small, processed in-request)");
    console.log("small import:", job && { status: job.status, ok: job.success_count, failed: job.failed_count });
  }
  if (args["import-large"]) {
    const started = performance.now();
    const job = await importFile(args["import-large"], "POST /imports/ (large, queued)");
    if (job) {
      let current = job;
      while (current.status === "QUEUED" || current.status === "PROCESSING") {
        await sleep(1000);
        const { text } = await call(admin, "GET /imports/{id}/ (poll)", "GET", `/api/v1/imports/${job.id}/`);
        current = JSON.parse(text);
        if (performance.now() - started > 600000) break;
      }
      const seconds = (performance.now() - started) / 1000;
      console.log(`large import: ${current.status}, ${current.success_count}/${current.total_rows} invited, ${seconds.toFixed(1)}s from upload to completion (${(current.total_rows / seconds).toFixed(1)} rows/s)`);
      samples.set("large import: time from upload to completion (ms)", { latencies: [seconds * 1000], statuses: new Map([[200, 1]]) });
    }
  }
}

// --------------------------------------------------------------------------- run
const scenarios = { browse, reveal, audit, import: imports };
const report = { startedAt: new Date().toISOString(), users: users.length, durationSeconds: duration / 1000, scenarios: {} };
for (const name of args.scenarios.split(",")) {
  samples.clear();
  const started = performance.now();
  console.log(`\n== ${name}`);
  await scenarios[name]();
  const seconds = (performance.now() - started) / 1000;
  const rows = summarize(seconds);
  report.scenarios[name] = { wallSeconds: +seconds.toFixed(1), rows };
  console.table(rows.map(({ label, requests, perSecond, p50, p95, p99, max, statuses }) => ({ label, requests, "req/s": perSecond, p50, p95, p99, max, statuses: JSON.stringify(statuses) })));
}
writeFileSync(args.out, JSON.stringify(report, null, 2));
console.log(`\nWrote ${args.out}`);
