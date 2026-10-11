// Layout regression check in a real browser: the window never scrolls, the sidebar stays put, and only <main> and the
// sidebar navigation scroll (each on its own), on desktop, a short desktop window and a phone-sized screen.
//
//   E2E_BASE_URL=http://localhost:5173 E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... E2E_SHOTS=some/dir npm run test:layout
//
// Works against the Vite dev server or the production stack. Needs an administrator (so every navigation entry shows).
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { after, before, describe, it } from "node:test";

import { chromium } from "playwright-core";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const ADMIN = { email: process.env.E2E_ADMIN_EMAIL, password: process.env.E2E_ADMIN_PASSWORD };
assert.ok(ADMIN.email && ADMIN.password, "set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD");
const SHOTS = process.env.E2E_SHOTS;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

const executablePath = process.env.E2E_BROWSER ?? [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].find((path) => existsSync(path));
assert.ok(executablePath, "no Edge/Chrome found; set E2E_BROWSER");

// Pages with enough content to overflow a short window, plus the table-heavy ones.
const PAGES = ["/", "/audit", "/vault", "/employees", "/reports", "/policy"];

let browser;
let context;
let page;
const problems = [];

const measure = () =>
  page.evaluate(() => {
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) };
    };
    const doc = document.scrollingElement;
    const main = document.querySelector("main#main");
    const aside = document.querySelector("aside#sidebar");
    const nav = aside?.querySelector("nav");
    return {
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      windowScrollable: doc.scrollHeight - window.innerHeight,
      windowOverflowX: doc.scrollWidth - window.innerWidth,
      windowY: window.scrollY,
      main: { scrollTop: main.scrollTop, scrollable: main.scrollHeight - main.clientHeight, overflowX: main.scrollWidth - main.clientWidth },
      aside: aside && getComputedStyle(aside).display !== "none" ? rect(aside) : null,
      nav: nav && aside && getComputedStyle(aside).display !== "none" ? { scrollTop: nav.scrollTop, scrollable: nav.scrollHeight - nav.clientHeight } : null,
      signOut: Array.from(document.querySelectorAll("aside button")).find((b) => b.textContent.trim() === "Sign out")?.getBoundingClientRect().bottom ?? null,
    };
  });

const shot = async (name) => SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png` });

async function go(path) {
  await page.goto(path);
  await page.locator("main#main h1").first().waitFor();
  await page.waitForLoadState("networkidle");
}

describe("app shell scrolling (real browser)", () => {
  before(async () => {
    // Playwright hides scrollbars in headless Chromium by default, which would make a "no visible scrollbar" check pass
    // vacuously; turn that off so a real scrollbar would take up space and show.
    browser = await chromium.launch({ executablePath, headless: true, args: ["--disable-gpu"], ignoreDefaultArgs: ["--hide-scrollbars"] });
    context = await browser.newContext({ ignoreHTTPSErrors: true, baseURL: BASE, viewport: { width: 1280, height: 560 } });
    page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error" && !/status of (401|403|404|423)/.test(message.text())) problems.push(`console: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("heading", { name: /^Welcome/ }).waitFor();
  });
  after(async () => {
    await context?.close();
    await browser?.close();
  });

  it("desktop: the window does not scroll and the sidebar fills the height, on every page", async () => {
    await page.setViewportSize({ width: 1280, height: 560 });
    for (const path of PAGES) {
      await go(path);
      const m = await measure();
      assert.ok(m.windowScrollable <= 1, `${path}: the window can scroll by ${m.windowScrollable}px`);
      assert.ok(m.windowOverflowX <= 0, `${path}: horizontal window overflow ${m.windowOverflowX}px`);
      assert.equal(m.aside.top, 0, `${path}: sidebar top`);
      assert.equal(m.aside.height, m.innerHeight, `${path}: sidebar should be exactly the window height`);
      assert.ok(m.signOut <= m.innerHeight, `${path}: the Sign out button is pushed off screen`);
    }
    await go("/");
    await shot("desktop-top");
  });

  it("desktop: scrolling the page moves only the page, not the sidebar", async () => {
    let checked = 0;
    for (const path of PAGES) {
      await go(path);
      const before = await measure();
      if (before.main.scrollable < 50) continue; // this page fits the window; nothing to scroll
      await page.evaluate(() => { document.querySelector("main#main").scrollTop = 100000; });
      const after = await measure();
      assert.ok(after.main.scrollTop > 0, `${path}: main did not scroll`);
      assert.equal(after.windowY, 0, `${path}: the window scrolled`);
      assert.deepEqual(after.aside, before.aside, `${path}: the sidebar moved while the page scrolled`);
      assert.equal(after.nav.scrollTop, before.nav.scrollTop, `${path}: the sidebar navigation scrolled with the page`);
      if (checked === 0) await shot("desktop-scrolled");
      checked += 1;
    }
    assert.ok(checked >= 2, `only ${checked} page(s) overflowed the window; the check needs longer content`);
  });

  it("opening another page starts at the top", async () => {
    await go("/audit");
    await page.evaluate(() => { document.querySelector("main#main").scrollTop = 100000; });
    assert.ok((await measure()).main.scrollTop > 0);
    await page.getByRole("link", { name: "Home", exact: true }).click();
    await page.getByRole("heading", { name: /^Welcome/ }).waitFor();
    assert.equal((await measure()).main.scrollTop, 0);
  });

  it("short window: the navigation scrolls by itself while the account block stays in view", async () => {
    await page.setViewportSize({ width: 1280, height: 380 });
    await go("/audit");
    const before = await measure();
    assert.ok(before.nav.scrollable > 0, "expected the navigation to overflow in a 380px window");
    assert.ok(before.signOut <= before.innerHeight, "the Sign out button is not visible");
    await page.evaluate(() => { document.querySelector("aside#sidebar nav").scrollTop = 100000; });
    const after = await measure();
    assert.ok(after.nav.scrollTop > 0, "the navigation did not scroll");
    assert.deepEqual(after.aside, before.aside, "the sidebar itself moved");
    assert.equal(after.main.scrollTop, before.main.scrollTop, "the page scrolled with the navigation");
    assert.equal(after.windowY, 0);
    await shot("desktop-short-nav-scrolled");
  });

  it("phone: the menu opens as a drawer, scrolls by itself, and nothing overflows sideways", async () => {
    await page.setViewportSize({ width: 390, height: 700 });
    for (const path of ["/", "/audit", "/vault", "/reports"]) {
      await go(path);
      const m = await measure();
      assert.ok(m.windowScrollable <= 1, `${path}: the window scrolls on a phone (${m.windowScrollable}px)`);
      assert.ok(m.windowOverflowX <= 0, `${path}: horizontal window overflow ${m.windowOverflowX}px on a phone`);
      assert.equal(m.aside, null, `${path}: the drawer should start closed`);
    }
    await go("/audit");
    await shot("phone-page");
    await page.getByRole("button", { name: "Menu" }).click();
    const open = await measure();
    assert.ok(open.aside && open.aside.height > 0, "the drawer did not open");
    assert.ok(open.aside.bottom <= open.innerHeight, "the drawer is taller than the screen");
    assert.ok(open.windowScrollable <= 1 && open.windowOverflowX <= 0);
    await shot("phone-drawer");
    // The drawer's navigation scrolls inside it (the account block stays pinned), or the drawer itself does if it must.
    assert.ok(open.nav.scrollable > 0 || (await page.evaluate(() => { const a = document.querySelector("aside#sidebar"); return a.scrollHeight > a.clientHeight; })), "the 15 entries fit, so this phone-sized screen cannot show the drawer scrolling");
    await page.evaluate(() => {
      document.querySelector("aside#sidebar nav").scrollTop = 100000;
      document.querySelector("aside#sidebar").scrollTop = 100000;
    });
    const scrolled = await page.evaluate(() => Math.max(document.querySelector("aside#sidebar nav").scrollTop, document.querySelector("aside#sidebar").scrollTop));
    assert.ok(scrolled > 0, "the drawer did not scroll by itself");
    const afterScroll = await measure();
    assert.equal(afterScroll.windowY, 0, "the window scrolled");
    assert.ok(afterScroll.signOut <= afterScroll.innerHeight, "Sign out left the screen while the drawer scrolled");
    await shot("phone-drawer-scrolled");
    await page.getByRole("link", { name: "Home", exact: true }).click();
    await page.getByRole("heading", { name: /^Welcome/ }).waitFor();
    assert.equal((await measure()).aside, null, "choosing a page should close the drawer");
  });

  it("dialogs stay inside the window and do not break the shell", async () => {
    await page.setViewportSize({ width: 1280, height: 560 });
    await go("/vault");
    await page.getByRole("button", { name: "New credential" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    const box = await dialog.boundingBox();
    assert.ok(box.y >= 0 && box.x >= 0 && box.x + box.width <= 1280, `dialog outside the window: ${JSON.stringify(box)}`);
    const m = await measure();
    assert.ok(m.windowScrollable <= 1 && m.windowOverflowX <= 0);
    await shot("dialog");
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "detached" });
  });

  it("no scrollbar is visible, yet wheel, keyboard and focus still scroll", async () => {
    await page.setViewportSize({ width: 1280, height: 420 });
    await go("/audit");
    const info = await page.evaluate(() =>
      Object.fromEntries(
        ["main#main", "aside#sidebar nav"].map((query) => {
          const el = document.querySelector(query);
          return [query, { gutter: el.offsetWidth - el.clientWidth, scrollbarWidth: getComputedStyle(el).scrollbarWidth, canScroll: el.scrollHeight > el.clientHeight }];
        }),
      ),
    );
    for (const [query, v] of Object.entries(info)) {
      assert.equal(v.gutter, 0, `${query}: a ${v.gutter}px scrollbar gutter is still reserved`);
      assert.equal(v.scrollbarWidth, "none", `${query}: scrollbar-width is ${v.scrollbarWidth}`);
      assert.ok(v.canScroll, `${query}: nothing to scroll in a 420px window; the check needs overflow`);
    }
    await shot("no-scrollbars-desktop");

    // Mouse wheel: over the page it scrolls the page only; over the navigation it scrolls the navigation only.
    await page.mouse.move(700, 250);
    await page.mouse.wheel(0, 400);
    await page.waitForFunction(() => document.querySelector("main#main").scrollTop > 0);
    assert.equal(await page.evaluate(() => document.querySelector("aside#sidebar nav").scrollTop), 0, "the wheel over the page scrolled the navigation");
    await page.mouse.move(100, 200);
    await page.mouse.wheel(0, 400);
    await page.waitForFunction(() => document.querySelector("aside#sidebar nav").scrollTop > 0);

    // Keyboard: PageDown / End / PageUp / Home move the page without any scrollbar to drag.
    await page.evaluate(() => { document.querySelector("main#main").scrollTop = 0; });
    await page.locator("main#main h1").click();
    await page.keyboard.press("PageDown");
    await page.waitForFunction(() => document.querySelector("main#main").scrollTop > 100);
    await page.keyboard.press("End");
    await page.waitForFunction(() => { const m = document.querySelector("main#main"); return m.scrollTop >= m.scrollHeight - m.clientHeight - 2; });
    await page.keyboard.press("Home");
    await page.waitForFunction(() => document.querySelector("main#main").scrollTop === 0);

    // Tabbing to something below the fold scrolls it into view and keeps a visible focus indicator.
    await page.evaluate(() => { document.querySelector("main#main").scrollTop = 0; document.activeElement?.blur(); });
    let focused = null;
    for (let i = 0; i < 60; i += 1) {
      await page.keyboard.press("Tab");
      focused = await page.evaluate(() => {
        const el = document.activeElement;
        const inMain = Boolean(el?.closest("main#main"));
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return { inMain, visible: r.top >= 0 && r.bottom <= window.innerHeight, outline: cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0, mainScrollTop: document.querySelector("main#main").scrollTop };
      });
      if (focused.inMain && focused.mainScrollTop > 0) break;
    }
    assert.ok(focused.mainScrollTop > 0, "tabbing through the page never scrolled it");
    assert.ok(focused.visible, "the focused element is not scrolled into view");
    assert.ok(focused.outline, "the focused element lost its focus indicator");
    await shot("keyboard-focus-scrolled");
  });

  it("phone: no scrollbar, and touch scrolling works for the page and for the drawer", async () => {
    const state = await context.storageState();
    const touch = await browser.newContext({ storageState: state, baseURL: BASE, viewport: { width: 390, height: 520 }, hasTouch: true, isMobile: true });
    const tp = await touch.newPage();
    tp.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
    try {
      await tp.goto("/audit");
      await tp.locator("main#main h1").first().waitFor();
      await tp.waitForLoadState("networkidle");
      const cdp = await touch.newCDPSession(tp);
      // A real touch drag (finger down, move, up). Touch points need ids and short pauses between moves to be delivered
      // as a scroll gesture in headless Chromium; Input.synthesizeScrollGesture is not delivered reliably.
      const swipeUp = async (x, y) => {
        await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y, id: 1 }] });
        for (let step = 1; step <= 12; step += 1) {
          await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y - step * 25, id: 1 }] });
          await tp.waitForTimeout(16);
        }
        await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      };
      const top = (query) => tp.evaluate((q) => document.querySelector(q).scrollTop, query);

      await swipeUp(200, 300);
      await tp.waitForFunction(() => document.querySelector("main#main").scrollTop > 0);
      assert.equal(await tp.evaluate(() => window.scrollY), 0, "the window scrolled instead of the page area");

      await tp.getByRole("button", { name: "Menu" }).click();
      const gutter = await tp.evaluate(() => { const n = document.querySelector("aside#sidebar nav"); return n.offsetWidth - n.clientWidth; });
      assert.equal(gutter, 0, "the drawer navigation reserves a scrollbar gutter");
      const before = await top("aside#sidebar nav");
      await swipeUp(150, 200);
      await tp.waitForFunction((b) => document.querySelector("aside#sidebar nav").scrollTop > b, before);
      await tp.screenshot({ path: SHOTS ? `${SHOTS}/phone-touch-drawer.png` : undefined });
    } finally {
      await touch.close();
    }
  });

  it("produced no console errors", () => {
    assert.deepEqual(problems, []);
  });
});
