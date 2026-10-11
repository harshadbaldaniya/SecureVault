import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp, unauthenticated } from "@/tests/utils";

describe("public landing page", () => {
  it("is what a signed-out visitor sees at the site root, with no sidebar and no protected requests", async () => {
    const { calls } = mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: /Your Credentials\. Protected\. Organized\. Under Control\./ })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })?.closest("aside")).toBeNull(); // the dashboard sidebar is not rendered
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(calls.map((c) => c.path).filter((p) => p !== "/auth/me/")).toEqual([]); // nothing but the session check
  });

  it("shows the dashboard, not the landing page, to a signed-in user", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: /^Welcome/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Under Control/ })).not.toBeInTheDocument();
  });

  it("sends every Sign In button to the sign-in screen and every Get Started button to the get-started page", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    const header = screen.getByRole("banner");
    const hero = screen.getByRole("heading", { level: 1 }).closest("section")!;
    const finalCta = screen.getByRole("heading", { name: /under control$/i, level: 2 }).closest("section")!;
    for (const [where, region] of [["navigation bar", header], ["hero", hero], ["closing call to action", finalCta]] as const) {
      const signIn = within(region).getByRole("link", { name: "Sign In" });
      const getStarted = within(region).getByRole("link", { name: "Get Started" });
      expect(signIn, `${where} Sign In`).toHaveAttribute("href", "/login");
      expect(getStarted, `${where} Get Started`).toHaveAttribute("href", "/get-started");
    }
  });

  it("opens the get-started page from the navigation bar and from the hero, and the sign-in screen from Sign In", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /auth/me/": unauthenticated });
    const { unmount } = renderApp("/");
    await user.click(within(await screen.findByRole("banner")).getByRole("link", { name: "Get Started" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Get started with SecureVault" })).toBeInTheDocument();
    unmount();

    const second = renderApp("/");
    const hero = (await screen.findByRole("heading", { level: 1, name: /Under Control/ })).closest("section")!;
    await user.click(within(hero).getByRole("link", { name: "Get Started" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Get started with SecureVault" })).toBeInTheDocument();
    second.unmount();

    renderApp("/");
    await user.click(within(await screen.findByRole("banner")).getByRole("link", { name: "Sign In" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("navigates to its own sections and only links to pages that exist", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    const header = screen.getByRole("navigation", { name: "Main" });
    expect(within(header).getByRole("link", { name: "Features" })).toHaveAttribute("href", "#features");
    expect(within(header).getByRole("link", { name: "Security" })).toHaveAttribute("href", "#security");
    expect(within(header).getByRole("link", { name: "How It Works" })).toHaveAttribute("href", "#how-it-works");
    for (const id of ["features", "security", "how-it-works"]) expect(document.getElementById(id)).not.toBeNull();
    const footer = screen.getByRole("navigation", { name: "Footer" });
    const targets = within(footer).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(targets.every((href) => href!.startsWith("#") || ["/login", "/forgot-password"].includes(href!))).toBe(true);
  });

  it("opens and closes an accessible mobile menu", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/");
    const toggle = await screen.findByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("navigation", { name: "Main mobile" });
    await user.click(within(menu).getByRole("link", { name: "Features" }));
    expect(screen.queryByRole("navigation", { name: "Main mobile" })).not.toBeInTheDocument();
  });

  it("makes no claim of certification, independent audit or zero-knowledge encryption", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/AES-256-GCM/);
    expect(text).toMatch(/not been through an independent security audit/);
    expect(text).toMatch(/not end-to-end or zero-knowledge/);
    expect(text).not.toMatch(/SOC ?2|ISO ?27001|HIPAA|GDPR[- ]compliant|FIPS/i);
  });

  it("keeps every other page protected for signed-out visitors", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/vault");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Under Control/ })).not.toBeInTheDocument();
  });
});

describe("get-started page", () => {
  it("is public, has no dashboard sidebar and makes no protected requests", async () => {
    const { calls } = mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/get-started");
    expect(await screen.findByRole("heading", { level: 1, name: "Get started with SecureVault" })).toBeInTheDocument();
    expect(document.querySelector("aside#sidebar")).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(calls.map((c) => c.path).filter((p) => p !== "/auth/me/")).toEqual([]);
  });

  it("explains that accounts come from an administrator's invitation and tells people who to contact", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/get-started");
    await screen.findByRole("heading", { level: 1 });
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/created through invitations from your organization.s administrator/);
    expect(text).toMatch(/no public sign-up/);
    expect(screen.getByRole("heading", { name: "Need access? Contact your administrator" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument(); // no fake registration form
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("offers 'Already have an account? Sign in' as the primary action", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/get-started");
    const action = await screen.findByRole("link", { name: "Already have an account? Sign in" });
    expect(action).toHaveAttribute("href", "/login");
    await user.click(action);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("links back to the landing sections with absolute paths so they work from this page", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/get-started");
    const header = await screen.findByRole("banner");
    expect(within(header).getByRole("link", { name: "Features" })).toHaveAttribute("href", "/#features");
    expect(within(header).getByRole("link", { name: "Sign In" })).toHaveAttribute("href", "/login");
    expect(within(header).getByRole("link", { name: "Get Started" })).toHaveAttribute("href", "/get-started");
  });
});
