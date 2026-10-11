// Real-browser check of the action hierarchy: buttons vs links vs toggles vs the file picker, their behavior, keyboard focus
// and phone layout.
//
//   E2E_BASE_URL=http://localhost:5173 E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... E2E_STATE=state.json E2E_SHOTS=dir npm run test:actions
//
// E2E_STATE (optional) saves the signed-in browser state after the first run and reuses it, so repeated runs do not
// register a new "device" and send new alerts for the same account each time.
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { after, before, describe, it } from "node:test";

import { chromium } from "playwright-core";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const ADMIN = { email: process.env.E2E_ADMIN_EMAIL, password: process.env.E2E_ADMIN_PASSWORD };
const STATE = process.env.E2E_STATE;
const SHOTS = process.env.E2E_SHOTS;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

const executablePath = process.env.E2E_BROWSER ?? [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].find((path) => existsSync(path));
assert.ok(executablePath, "no Edge/Chrome found; set E2E_BROWSER");

const WHITE = "rgb(255, 255, 255)";
const BRAND = "rgb(37, 99, 235)"; // brand-600
let browser;
let anon;
let signed;
const problems = [];

const watch = (page) => {
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of (401|403|404|423)/.test(m.text())) problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
};
const shot = async (page, name) => SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
const style = (locator, props) =>
  locator.evaluate((el, names) => {
    const cs = getComputedStyle(el);
    return Object.fromEntries(names.map((n) => [n, cs[n]]));
  }, props);
const overflowX = (page) => page.evaluate(() => ({ window: document.scrollingElement.scrollWidth - innerWidth, main: (document.querySelector("main#main") ?? document.body).scrollWidth - (document.querySelector("main#main") ?? document.body).clientWidth }));

describe("action hierarchy in a real browser", () => {
  before(async () => {
    browser = await chromium.launch({ executablePath, headless: true, args: ["--disable-gpu"], ignoreDefaultArgs: ["--hide-scrollbars"] });
    anon = await (await browser.newContext({ ignoreHTTPSErrors: true, baseURL: BASE, viewport: { width: 1280, height: 720 } })).newPage();
    watch(anon);

    const options = { ignoreHTTPSErrors: true, baseURL: BASE, viewport: { width: 1280, height: 720 } };
    if (STATE && existsSync(STATE)) options.storageState = STATE;
    const context = await browser.newContext(options);
    signed = await context.newPage();
    watch(signed);
    await signed.goto("/");
    if (!(await signed.getByRole("heading", { name: /^Welcome/ }).isVisible().catch(() => false))) {
      assert.ok(ADMIN.email && ADMIN.password, "no saved session: set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD");
      await signed.goto("/login");
      await signed.getByLabel("Email").fill(ADMIN.email);
      await signed.getByLabel("Password").fill(ADMIN.password);
      await signed.getByRole("button", { name: "Sign in" }).click();
      await signed.getByRole("heading", { name: /^Welcome/ }).waitFor();
      if (STATE) await context.storageState({ path: STATE });
    }
  });
  after(async () => browser?.close());

  it("password reset: 'Back to sign in' is a secondary button, the confirmation stays a status, and navigation works", async () => {
    await anon.goto("/forgot-password");
    const back = anon.getByRole("link", { name: "Back to sign in" });
    const s = await style(back, ["backgroundColor", "minHeight", "borderRadius", "fontWeight"]);
    assert.equal(s.backgroundColor, WHITE, "secondary buttons have a white surface");
    assert.ok(parseFloat(s.minHeight) >= 40, `target height ${s.minHeight}`);
    assert.ok(await back.locator("svg").count(), "expected the left-arrow icon");
    await shot(anon, "forgot-password");

    // The generic confirmation is a status message, not a button, and does not reveal whether the account exists.
    await anon.getByLabel("Email").fill("nobody-at-all@example.test");
    await anon.getByRole("button", { name: "Send reset link" }).click();
    const status = anon.getByRole("status").filter({ hasText: "If an account exists for that email" });
    await status.waitFor();
    assert.equal(await status.getByRole("link").count() + (await status.getByRole("button").count()), 0, "the confirmation must not be an action");
    await shot(anon, "forgot-password-sent");

    await anon.getByRole("link", { name: "Back to sign in" }).click();
    await anon.getByRole("heading", { name: "Sign in" }).waitFor();
    assert.match(anon.url(), /\/login$/);
    // "Forgot your password?" stays a lightweight inline link.
    const forgot = anon.getByRole("link", { name: "Forgot your password?" });
    assert.notEqual((await style(forgot, ["backgroundColor"])).backgroundColor, WHITE);
    await shot(anon, "login");
  });

  it("dashboard: 2FA notice, chart/table control, 'Review alerts' and 'Open the audit log'", async () => {
    await signed.goto("/");
    await signed.getByRole("heading", { name: "Organization security" }).waitFor();
    await signed.waitForLoadState("networkidle");

    // The security notice stays a distinct status block with the action aligned inside it.
    const notice = signed.getByRole("status").filter({ hasText: "Two-step verification is off" });
    const turnOn = notice.getByRole("link", { name: "Turn it on" });
    assert.equal((await style(turnOn, ["backgroundColor"])).backgroundColor, WHITE);
    const [nb, ab] = await Promise.all([notice.boundingBox(), turnOn.boundingBox()]);
    assert.ok(ab.x >= nb.x && ab.x + ab.width <= nb.x + nb.width && ab.y >= nb.y && ab.y + ab.height <= nb.y + nb.height, "the action is not inside the notice");
    await shot(signed, "dashboard-top");

    // Chart / Table is a two-option control that marks the selected view.
    const figure = signed.getByRole("figure").first();
    const group = figure.getByRole("group", { name: /view$/ });
    assert.equal(await group.getByRole("button", { name: "Chart" }).getAttribute("aria-pressed"), "true");
    await group.getByRole("button", { name: "Table" }).click();
    assert.equal(await group.getByRole("button", { name: "Table" }).getAttribute("aria-pressed"), "true");
    await figure.getByRole("table").waitFor();
    await group.getByRole("button", { name: "Chart" }).click();
    assert.equal(await figure.getByRole("table").count(), 0);

    const review = signed.getByRole("link", { name: "Review alerts" });
    await review.scrollIntoViewIfNeeded();
    assert.equal((await style(review, ["backgroundColor"])).backgroundColor, WHITE);
    await shot(signed, "dashboard-alerts");
    const audit = signed.getByRole("link", { name: "Open the audit log" });
    await audit.scrollIntoViewIfNeeded();
    assert.equal((await style(audit, ["backgroundColor"])).backgroundColor, WHITE);
    assert.ok(await audit.locator("svg").count(), "expected the document icon");
    await shot(signed, "dashboard-events");

    await audit.click();
    await signed.getByRole("heading", { name: "Audit log" }).waitFor();
    await signed.goto("/");
    await signed.getByRole("link", { name: "Review alerts" }).click();
    await signed.getByRole("heading", { name: "Security alerts" }).waitFor();
    await signed.goto("/");
    await notice.getByRole("link", { name: "Turn it on" }).click();
    await signed.getByRole("heading", { name: /Account security|Security/ }).first().waitFor();
    assert.match(signed.url(), /\/security$/);
  });

  it("employee import: template download, file picker, validation and the primary action", async () => {
    await signed.goto("/employees/import");
    await signed.getByRole("heading", { name: "Employee import" }).waitFor();

    const template = signed.getByRole("link", { name: "Download the template" });
    assert.equal((await style(template, ["backgroundColor"])).backgroundColor, WHITE);
    const [download] = await Promise.all([signed.waitForEvent("download"), template.click()]);
    assert.match(download.suggestedFilename(), /\.xlsx$/);

    // A real button and a readable status instead of the native "Choose File / No file chosen".
    assert.equal(await signed.getByText("No file chosen").count(), 0);
    await signed.getByText("No file selected").waitFor();
    const choose = signed.locator("label", { hasText: "Choose file" });
    assert.equal((await style(choose, ["backgroundColor"])).backgroundColor, WHITE);
    const primary = signed.getByRole("button", { name: "Upload and import" });
    assert.equal((await style(primary, ["backgroundColor"])).backgroundColor, BRAND, "Upload and import is the primary action");
    await shot(signed, "import-empty");

    // Keyboard: Tab reaches the (visually replaced) native input and the button shows a focus ring.
    await signed.keyboard.press("Tab");
    let focused = false;
    for (let i = 0; i < 40 && !focused; i += 1) {
      focused = await signed.evaluate(() => document.activeElement?.getAttribute("type") === "file");
      if (!focused) await signed.keyboard.press("Tab");
    }
    assert.ok(focused, "could not reach the file input with Tab");
    const ring = await style(choose, ["outlineStyle", "outlineWidth"]);
    assert.notEqual(ring.outlineStyle, "none", "no focus indicator on the choose-file button");
    assert.ok(parseFloat(ring.outlineWidth) >= 2);
    await shot(signed, "import-focus");

    let posts = 0;
    await signed.route("**/api/v1/imports/", (route) => {
      if (route.request().method() === "POST") {
        posts += 1;
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ id: "job-1", file_name: "people.xlsx", status: "COMPLETED", total_rows: 3, success_count: 3, failed_count: 0, errors: [], file_error: "", uploaded_by_name: "E2E", retry_of: null, created_at: new Date().toISOString(), started_at: null, finished_at: null }),
        });
      }
      return route.fallback();
    });

    // Wrong type: the filename is shown, validation refuses it, and nothing is sent.
    await signed.setInputFiles('input[type="file"]', { name: "people.csv", mimeType: "text/csv", buffer: Buffer.from("a,b") });
    await signed.getByText("people.csv").waitFor();
    await primary.click();
    await signed.getByRole("alert").filter({ hasText: "Only .xlsx workbooks are accepted." }).waitFor();
    // Too large (2 MB limit).
    await signed.setInputFiles('input[type="file"]', { name: "huge.xlsx", mimeType: "application/octet-stream", buffer: Buffer.alloc(3 * 1024 * 1024) });
    await primary.click();
    await signed.getByRole("alert").filter({ hasText: "larger than 2 MB" }).waitFor();
    assert.equal(posts, 0, "an invalid file must not be uploaded");
    await shot(signed, "import-validation");

    // A valid workbook is sent as multipart and the result is shown (the server call is stubbed so no one is invited).
    await signed.setInputFiles('input[type="file"]', { name: "people.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("PK") });
    await signed.getByText("people.xlsx").first().waitFor();
    await primary.click();
    await signed.getByText(/3 of 3 employees invited/).waitFor();
    assert.equal(posts, 1);
    await shot(signed, "import-done");
    await signed.unroute("**/api/v1/imports/");
  });

  it("phone: the same actions wrap without clipping or sideways overflow", async () => {
    await signed.setViewportSize({ width: 390, height: 780 });
    for (const [path, ready] of [["/", { name: "Organization security" }], ["/employees/import", { name: "Employee import" }]]) {
      await signed.goto(path);
      await signed.getByRole("heading", ready).waitFor();
      await signed.waitForLoadState("networkidle");
      const o = await overflowX(signed);
      assert.ok(o.window <= 0 && o.main <= 1, `${path}: horizontal overflow ${JSON.stringify(o)}`);
    }
    await shot(signed, "phone-import");
    await signed.goto("/");
    await signed.getByRole("heading", { name: "Organization security" }).waitFor();
    const notice = signed.getByRole("status").filter({ hasText: "Two-step verification is off" });
    const [nb, ab] = await Promise.all([notice.boundingBox(), notice.getByRole("link", { name: "Turn it on" }).boundingBox()]);
    assert.ok(ab.x >= nb.x && ab.x + ab.width <= nb.x + nb.width + 0.5, "the notice action is clipped on a phone");
    assert.ok(ab.height >= 32, `touch target ${ab.height}px`);
    await shot(signed, "phone-dashboard");

    await anon.setViewportSize({ width: 390, height: 780 });
    await anon.goto("/forgot-password");
    const back = await anon.getByRole("link", { name: "Back to sign in" }).boundingBox();
    assert.ok(back.height >= 40 && back.x >= 0 && back.x + back.width <= 390, "the back button is clipped on a phone");
    await shot(anon, "phone-forgot-password");
  });

  it("no console errors", () => assert.deepEqual(problems, []));
});
