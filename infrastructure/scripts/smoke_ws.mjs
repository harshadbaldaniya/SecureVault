// WebSocket handshake checks against a running stack (used by smoke_prod.sh; Node 22+, no dependencies).
//
//   node infrastructure/scripts/smoke_ws.mjs <wss-url> <allowed-origin> <session-cookie-value>
//
// Set NODE_TLS_REJECT_UNAUTHORIZED=0 when the stack uses a self-signed certificate.
//
// Expectations:
//   1. no session cookie            -> the socket is accepted only to be closed with application code 4401
//   2. valid session, allowed origin -> a "hello" message, then "pong" for a ping
//   3. valid session, foreign origin -> the handshake itself is refused (cross-site WebSocket hijacking)
const [url, origin, session] = process.argv.slice(2);
if (!url || !origin || !session) {
  console.error("usage: node smoke_ws.mjs <wss-url> <allowed-origin> <session-cookie-value>");
  process.exit(2);
}

function attempt(headers) {
  return new Promise((resolve) => {
    const ws = new WebSocket(url, { headers });
    const result = { opened: false, messages: [], closeCode: null };
    const timer = setTimeout(() => {
      result.timedOut = true;
      ws.close();
      resolve(result);
    }, 6000);
    ws.addEventListener("open", () => {
      result.opened = true;
    });
    ws.addEventListener("message", (event) => result.messages.push(JSON.parse(event.data)));
    ws.addEventListener("close", (event) => {
      result.closeCode = event.code;
      clearTimeout(timer);
      resolve(result);
    });
    ws.addEventListener("error", () => {});
  });
}

const checks = [];
function check(name, pass, detail) {
  checks.push({ name, pass: Boolean(pass) });
  console.log(`${pass ? "PASS" : "FAIL"} ${name}${pass ? "" : ` -> ${JSON.stringify(detail)}`}`);
}

const anonymous = await attempt({ Origin: origin });
check("anonymous socket is closed with 4401", anonymous.opened && anonymous.closeCode === 4401 && anonymous.messages.length === 0, anonymous);

// The socket stays open once authenticated: wait for hello and a pong to a ping, then close it ourselves.
const live = await new Promise((resolve) => {
  const ws = new WebSocket(url, { headers: { Origin: origin, Cookie: `sv_session=${session}` } });
  const seen = [];
  const timer = setTimeout(() => { ws.close(); resolve(seen); }, 4000);
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    seen.push(msg.type);
    if (msg.type === "hello") ws.send(JSON.stringify({ type: "ping" }));
    if (msg.type === "pong") { clearTimeout(timer); ws.close(); resolve(seen); }
  });
  ws.addEventListener("error", () => {});
});
check("authenticated socket receives hello, then pong", live.includes("hello") && live.includes("pong"), live);

const foreign = await attempt({ Origin: "https://evil.example", Cookie: `sv_session=${session}` });
check("foreign Origin is refused at the handshake", !foreign.opened, foreign);

process.exit(checks.every((c) => c.pass) ? 0 : 1);
