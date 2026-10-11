import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeMe, mockFetch, renderApp } from "@/tests/utils";
import type { Credential } from "@/types/api";

const SECRET = "Xq7!Plaintext-Marker-9137";
const page = <T,>(results: T[]) => ({ body: { count: results.length, next: null, previous: null, results } });
const policy = {
  id: "p", name: "Default", min_password_length: 14, require_uppercase: true, require_numbers: true, require_symbols: true,
  max_password_age_days: 90, expiry_warning_days: 14, allow_view_once: true, max_share_duration_days: 30,
  require_device_trust: false, require_mfa: false, updated_at: "2026-10-11T00:00:00Z",
};

function credential(overrides: Partial<Credential> = {}): Credential {
  return {
    id: "c1", title: "Prod DB", username: "svc_app", service: null, service_name: null, secret_type: "PASSWORD",
    category: "", tags: ["prod"], expires_at: "2027-01-01", entropy_bits: 120, strength: "very_strong",
    is_expired: false, expires_soon: false, password_age_days: 3, reuse_count: 0, owner_name: "Eve",
    permissions: ["COPY", "DELETE", "EDIT", "REVEAL", "SHARE", "VIEW"], archived_at: null,
    created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", password_changed_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

function baseRoutes(items: Credential[] = [credential()]) {
  return {
    "GET /auth/me/": { body: makeMe("EMPLOYEE") },
    "GET /auth/csrf/": { status: 204 },
    "GET /vault/credentials/": page(items),
    "GET /services/": page([]),
    "GET /policy/": { body: policy },
  };
}

function installClipboard() {
  const clipboard = { text: "", writeText: vi.fn(async (t: string) => { clipboard.text = t; }), readText: vi.fn(async () => clipboard.text) };
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
  return clipboard;
}

describe("credentials vault", () => {
  afterEach(() => vi.useRealTimers());

  it("lists metadata with hygiene badges and never renders a secret", async () => {
    mockFetch(baseRoutes([credential(), credential({ id: "c2", title: "Old key", strength: "weak", is_expired: true, reuse_count: 2 })]));
    renderApp("/vault");
    const row = (await screen.findByText("Old key")).closest("tr")!;
    expect(within(row).getByText("Weak")).toBeInTheDocument();
    expect(within(row).getByText("Expired")).toBeInTheDocument();
    expect(within(row).getByText("Reused ×3")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  describe("with fake timers", () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));

    it("reveals on click, audits through the API, and hides the secret again after 30 seconds", async () => {
      const { calls } = mockFetch({ ...baseRoutes(), "POST /vault/credentials/c1/reveal/": { body: { password: SECRET } } });
      renderApp("/vault");
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await user.click(await screen.findByRole("button", { name: "Reveal Prod DB" }));

      expect(await screen.findByText(SECRET)).toBeInTheDocument();
      expect(calls.find((c) => c.path === "/vault/credentials/c1/reveal/")?.body).toEqual({ purpose: "view" });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      await waitFor(() => expect(screen.queryByText(SECRET)).not.toBeInTheDocument());
      expect(document.body.innerHTML).not.toContain(SECRET);
      expect(localStorage.length + sessionStorage.length).toBe(0);
    });

    it("copies through a separate audited call and clears the clipboard after 30 seconds", async () => {
      const { calls } = mockFetch({ ...baseRoutes(), "POST /vault/credentials/c1/reveal/": { body: { password: SECRET } } });
      renderApp("/vault");
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const clipboard = installClipboard(); // after setup(): user-event installs its own clipboard stub
      await user.click(await screen.findByRole("button", { name: "Copy Prod DB" }));

      expect(await screen.findByText(/best-effort/)).toBeInTheDocument();
      expect(clipboard.text).toBe(SECRET);
      expect(calls.find((c) => c.path === "/vault/credentials/c1/reveal/")?.body).toEqual({ purpose: "copy" });
      expect(screen.queryByText(SECRET)).not.toBeInTheDocument(); // copying never displays it

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(clipboard.text).toBe("");
      expect(await screen.findByText(/Clipboard cleared/)).toBeInTheDocument();
    });
  });

  it("explains when the browser blocks the clipboard", async () => {
    mockFetch({ ...baseRoutes(), "POST /vault/credentials/c1/reveal/": { body: { password: SECRET } } });
    renderApp("/vault");
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    await user.click(await screen.findByRole("button", { name: "Copy Prod DB" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/blocked clipboard access/);
  });

  it("shows the server's refusal (e.g. lockdown or permission) instead of a secret", async () => {
    mockFetch({
      ...baseRoutes(),
      "POST /vault/credentials/c1/reveal/": { status: 403, body: { error: { code: "permission_denied", message: "You do not have permission to do this." } } },
    });
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Reveal Prod DB" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have permission to do this.");
  });

  it("creates a credential with a generated password, live strength feedback and normalised tags", async () => {
    const { calls } = mockFetch({ ...baseRoutes([]), "POST /vault/credentials/": { status: 201, body: credential() } });
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "New credential" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Title"), "Billing DB");
    await user.type(within(dialog).getByLabelText("Tags"), "Prod, db");
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));

    const secretField = within(dialog).getByLabelText("Secret") as HTMLInputElement;
    const generated = secretField.value;
    expect(generated).toHaveLength(20);
    expect(secretField.type).toBe("text"); // generated value is shown so the user can see what was created
    expect(within(dialog).getByText(/Strength:/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Save credential" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/vault/credentials/")).toBe(true));
    const body = calls.find((c) => c.method === "POST" && c.path === "/vault/credentials/")!.body as Record<string, unknown>;
    expect(body).toMatchObject({ title: "Billing DB", tags: ["prod", "db"], secret_type: "PASSWORD", password: generated, service: null });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body.innerHTML).not.toContain(generated); // the form was reset; the secret is gone from the page
  });

  it("blocks a password that breaks the organization policy before calling the server", async () => {
    const { calls } = mockFetch(baseRoutes([]));
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "New credential" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Title"), "Weak one");
    await user.type(within(dialog).getByLabelText("Secret"), "short");
    await user.click(within(dialog).getByRole("button", { name: "Save credential" }));
    expect(await within(dialog).findByText(/Use at least 14 characters/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/vault/credentials/")).toBe(false);
  });

  it("edits metadata without sending a secret when the secret field is left blank", async () => {
    const { calls } = mockFetch({ ...baseRoutes(), "PATCH /vault/credentials/c1/": { body: credential({ title: "Renamed" }) } });
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit Prod DB" }));
    const dialog = await screen.findByRole("dialog");
    const title = within(dialog).getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Renamed");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const body = calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(body.title).toBe("Renamed");
    expect(body).not.toHaveProperty("password");
    expect(body).not.toHaveProperty("expires_at"); // unchanged expiry is not re-sent
  });

  it("asks for confirmation before archiving", async () => {
    const { calls } = mockFetch({ ...baseRoutes(), "DELETE /vault/credentials/c1/": { status: 204 } });
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Archive Prod DB" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/vault/credentials/c1/")).toBe(true));
  });

  it("only offers the actions the server says this user may perform", async () => {
    mockFetch(baseRoutes([credential({ title: "Shared with me", permissions: ["COPY", "REVEAL", "VIEW"] })]));
    renderApp("/vault");
    expect(await screen.findByRole("button", { name: "Reveal Shared with me" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit Shared with me" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive Shared with me" })).not.toBeInTheDocument();
  });
});

describe("secure notes", () => {
  it("opens note content on click and never lists it", async () => {
    const note = { id: "n1", title: "Runbook", category: "Ops", tags: [], expires_at: null, owner_name: "Eve", permissions: ["COPY", "DELETE", "EDIT", "REVEAL", "SHARE", "VIEW"], archived_at: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /auth/csrf/": { status: 204 },
      "GET /vault/notes/": page([note]),
      "POST /vault/notes/n1/reveal/": { body: { content: "root token: abc-123" } },
    });
    renderApp("/vault/notes");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Open Runbook" }));
    expect(await screen.findByText("root token: abc-123")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/vault/notes/n1/reveal/")?.body).toEqual({ purpose: "view" });
  });
});
