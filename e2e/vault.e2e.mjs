// Real-browser end-to-end check of the production stack: React SPA <-> nginx (TLS, CSP) <-> Daphne/Django <->
// PostgreSQL/Redis, including the WebSocket. Uses the system Edge or Chrome through playwright-core (no browser download).
//
//   E2E_BASE_URL=https://localhost:18443 E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... npm test
//
// The admin account must already exist (manage.py bootstrap_org). Employees are created through the UI/API by the test.
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { after, before, describe, it } from "node:test";

import { chromium } from "playwright-core";

const BASE = process.env.E2E_BASE_URL ?? "https://localhost:18443";
const ADMIN = { email: process.env.E2E_ADMIN_EMAIL, password: process.env.E2E_ADMIN_PASSWORD };
assert.ok(ADMIN.email && ADMIN.password, "set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD");

const BROWSERS = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
];
const executablePath = process.env.E2E_BROWSER ?? BROWSERS.find((path) => existsSync(path));
assert.ok(executablePath, "no Edge/Chrome found; set E2E_BROWSER");

const run = Date.now().toString(36);
const SECRET = `E2e!${run}-Plaintext-Marker-7731`;
const TITLE = `E2E DB ${run}`;
const EMPLOYEE = { email: `e2e.${run}@example.test`, name: `Erin E2E ${run}`, password: `Emp-${run}-Passphrase-Strong-91!` };

let browser;
const contexts = [];
const problems = []; // console errors, CSP violations, page errors, unexpected failed requests

async function newPage() {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, baseURL: BASE });
  contexts.push(context);
  const page = await context.newPage();
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" || /content security policy|refused to/i.test(text)) problems.push(`console: ${text}`);
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return { context, page };
}

async function signIn(page, email, password) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: /^Welcome/ }).waitFor();
}

describe("SecureVault in a real browser (production stack)", () => {
  let admin;
  let employee;
  let inviteUrl;

  before(async () => {
    browser = await chromium.launch({ executablePath, headless: true, args: ["--disable-gpu"] });
    admin = await newPage();
  });
  after(async () => {
    for (const context of contexts) await context.close().catch(() => {});
    await browser?.close();
  });

  it("serves the app under a strict CSP with no console errors, and rejects bad credentials", async () => {
    const { page } = admin;
    const response = await page.goto("/login");
    const csp = response.headers()["content-security-policy"];
    assert.match(csp, /default-src 'self'/);
    assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval/);
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill("definitely-the-wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("alert").filter({ hasText: "Invalid email or password." }).waitFor();
  });

  it("signs the administrator in; the session cookie is invisible to page scripts", async () => {
    const { page, context } = admin;
    await signIn(page, ADMIN.email, ADMIN.password);
    assert.doesNotMatch(await page.evaluate(() => document.cookie), /sv_session/);
    const cookies = await context.cookies();
    const session = cookies.find((cookie) => cookie.name === "sv_session");
    assert.ok(session.httpOnly && session.secure && session.sameSite === "Strict", JSON.stringify(session));
  });

  it("stores a credential: the list shows metadata only and the secret never reaches the page", async () => {
    const { page } = admin;
    await page.getByRole("link", { name: "Credentials", exact: true }).click();
    await page.getByRole("button", { name: "New credential" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Title").fill(TITLE);
    await dialog.getByLabel("Username / account").fill("svc_e2e");
    await dialog.getByLabel("Secret", { exact: true }).fill(SECRET);
    await dialog.getByRole("button", { name: "Save credential" }).click();
    await page.getByRole("button", { name: `Reveal ${TITLE}` }).waitFor();
    assert.ok(!(await page.content()).includes(SECRET), "secret present in the DOM after saving");
  });

  it("reveals the secret on demand, keeps it out of web storage, and closes the dialog", async () => {
    const { page } = admin;
    await page.getByRole("button", { name: `Reveal ${TITLE}` }).click();
    const shown = page.getByLabel("Secret value");
    await shown.waitFor();
    assert.equal((await shown.textContent()).trim(), SECRET);
    const storage = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }]));
    assert.ok(!storage.includes(SECRET), "secret found in web storage");
    await page.getByRole("button", { name: "Done" }).click();
    await shown.waitFor({ state: "detached" });
    assert.ok(!(await page.content()).includes(SECRET), "secret left in the DOM after closing");
  });

  it("invites an employee; the one-time link activates the account", async () => {
    const { page, context } = admin;
    const csrf = (await context.cookies()).find((cookie) => cookie.name === "sv_csrftoken").value;
    const created = await page.request.post("/api/v1/invitations/", {
      headers: { "X-CSRFToken": csrf, Origin: BASE },
      data: { email: EMPLOYEE.email, full_name: EMPLOYEE.name, role: "EMPLOYEE" },
    });
    assert.equal(created.status(), 201);
    inviteUrl = (await created.json()).invite_url;
    assert.match(inviteUrl, /#token=/); // the token travels in the fragment, so it never reaches a server log

    employee = await newPage();
    await employee.page.goto(inviteUrl);
    await employee.page.getByLabel("New password", { exact: true }).fill(EMPLOYEE.password);
    await employee.page.getByLabel("Confirm new password").fill(EMPLOYEE.password);
    await employee.page.getByRole("button", { name: "Activate account" }).click();
    await employee.page.getByText("Account activated").waitFor();
    // The link is single-use. (about:blank first: a hash-only navigation would not reload the app.)
    await employee.page.goto("about:blank");
    await employee.page.goto(inviteUrl);
    await employee.page.getByLabel("New password", { exact: true }).fill(EMPLOYEE.password);
    await employee.page.getByLabel("Confirm new password").fill(EMPLOYEE.password);
    await employee.page.getByRole("button", { name: "Activate account" }).click();
    await employee.page.getByRole("alert").waitFor();
    await signIn(employee.page, EMPLOYEE.email, EMPLOYEE.password);
  });

  it("shares a credential as view-once: the employee can reveal it exactly once", async () => {
    const { page } = admin;
    await page.getByRole("button", { name: `Share ${TITLE}` }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Share with").fill(EMPLOYEE.name.slice(0, 8));
    await dialog.getByRole("list", { name: "Matching people" }).getByRole("button", { name: new RegExp(EMPLOYEE.name) }).click();
    await dialog.getByLabel(/View once/).check();
    await dialog.getByRole("button", { name: "Share", exact: true }).click();
    await dialog.getByText(/Access granted|shared/i).first().waitFor();
    await dialog.getByRole("button", { name: "Close" }).click();

    const { page: emp } = employee;
    await emp.getByRole("link", { name: "Credentials", exact: true }).click();
    await emp.getByRole("button", { name: `Reveal ${TITLE}` }).click();
    assert.equal((await emp.getByLabel("Secret value").textContent()).trim(), SECRET);
    await emp.getByRole("button", { name: "Done" }).click();

    await emp.getByRole("button", { name: `Reveal ${TITLE}` }).click();
    await emp.getByRole("alert").filter({ hasText: "already been used" }).waitFor();
  });

  it("lockdown reaches a connected employee's browser within seconds, and the server refuses secrets", async () => {
    const { page: emp } = employee;
    await emp.goto("/");
    await emp.getByRole("heading", { name: /^Welcome/ }).waitFor();
    await emp.waitForTimeout(1500); // let the WebSocket connect

    const { page } = admin;
    await page.getByRole("link", { name: "Emergency lockdown" }).click();
    await page.getByLabel("Reason").fill("End-to-end test of emergency lockdown");
    await page.getByLabel("Your password").fill(ADMIN.password);
    await page.getByRole("button", { name: /Activate lockdown/ }).click();
    const started = Date.now();
    await page.getByRole("dialog").getByRole("button", { name: "Lock down now" }).click();

    await emp.getByRole("heading", { name: "Sign in" }).waitFor({ timeout: 10000 });
    const elapsed = Date.now() - started;
    console.log(`lockdown reached the employee's browser ${elapsed} ms after the administrator clicked`);
    assert.ok(elapsed < 5000, `took ${elapsed} ms`);
    await emp.getByText(/emergency lockdown/i).first().waitFor();

    // The administrator keeps the session but cannot reveal secrets either.
    await page.getByRole("link", { name: "Credentials", exact: true }).click();
    await page.getByRole("button", { name: `Reveal ${TITLE}` }).click();
    await page.getByRole("alert").first().waitFor();
    assert.ok(!(await page.content()).includes(SECRET));
  });

  it("recorded all of this in an audit log that contains no secret", async () => {
    const { page } = admin;
    const body = await page.evaluate(async () => (await fetch("/api/v1/audit-logs/?page_size=100")).text());
    assert.match(body, /"action":\s*"REVEAL"/);
    assert.match(body, /"action":\s*"LOCKDOWN"/);
    assert.ok(!body.includes(SECRET));
  });

  it("produced no console errors or CSP violations anywhere", () => {
    const unexpected = problems.filter((text) => !/status of (401|403|410|423)|Failed to load resource/i.test(text));
    assert.deepEqual(unexpected, []);
  });
});
