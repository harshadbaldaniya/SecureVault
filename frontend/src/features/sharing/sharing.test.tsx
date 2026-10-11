import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp } from "@/tests/utils";
import type { Credential, DelegationTree } from "@/types/api";

const page = <T,>(results: T[]) => ({ body: { count: results.length, next: null, previous: null, results } });
const policy = {
  id: "p", name: "Default", min_password_length: 14, require_uppercase: true, require_numbers: true, require_symbols: true,
  max_password_age_days: 90, expiry_warning_days: 14, allow_view_once: true, max_share_duration_days: 30,
  require_device_trust: false, require_mfa: false, updated_at: "2026-10-11T00:00:00Z",
};

function credential(overrides: Partial<Credential> = {}): Credential {
  return {
    id: "c1", title: "Prod DB", username: "svc", service: null, service_name: null, secret_type: "PASSWORD", category: "",
    tags: [], expires_at: null, entropy_bits: 120, strength: "very_strong", is_expired: false, expires_soon: false,
    password_age_days: 1, reuse_count: 0, owner_name: "Eve Example", permissions: ["COPY", "DELETE", "EDIT", "REVEAL", "SHARE", "VIEW"],
    access: "owner", sharing: null, requestable: false, archived_at: null, created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z", password_changed_at: "2026-10-01T00:00:00Z", ...overrides,
  };
}

const tree: DelegationTree = {
  credential: "c1",
  credential_title: "Prod DB",
  owner: "Eve Example",
  nodes: [
    { id: "s1", parent_share: null, depth: 0, grantor: "Eve Example", grantee: "Bob", grantee_email: "bob@x.test", permission: "SHARE", state: "ACTIVE", expires_at: "2026-11-01T00:00:00Z", is_view_once: false, created_at: "2026-10-01T00:00:00Z" },
    { id: "s2", parent_share: "s1", depth: 1, grantor: "Bob", grantee: "Carol", grantee_email: "carol@x.test", permission: "VIEW", state: "ACTIVE", expires_at: "2026-11-01T00:00:00Z", is_view_once: true, created_at: "2026-10-02T00:00:00Z" },
  ],
};

function routes(extra = {}) {
  return {
    "GET /auth/me/": { body: makeMe("EMPLOYEE") },
    "GET /auth/csrf/": { status: 204 },
    "GET /vault/credentials/": page([credential()]),
    "GET /services/": page([]),
    "GET /policy/": { body: policy },
    "GET /shares/tree/c1/": { body: tree },
    "GET /people/": page([{ id: "u-bob", full_name: "Bob", email: "bob@x.test", department_name: "Ops" }]),
    ...extra,
  };
}

describe("sharing a credential", () => {
  it("shows the delegation tree with nesting and state", async () => {
    mockFetch(routes());
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Share Prod DB" }));
    const treeEl = await screen.findByRole("tree", { name: "Delegation tree" });
    const items = within(treeEl).getAllByRole("treeitem");
    expect(items).toHaveLength(2);
    expect(items[1]).toHaveAttribute("aria-level", "2"); // Carol's grant is nested under Bob's
    expect(within(items[1]!).getByText("View once")).toBeInTheDocument();
  });

  it("creates a view-once share as VIEW and tells the user what view-once cannot prevent", async () => {
    const { calls } = mockFetch(routes({ "POST /vault/credentials/c1/share/": { status: 201, body: {} } }));
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Share Prod DB" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Share with"), "bo");
    await user.click(await within(dialog).findByRole("button", { name: /bob@x\.test/ }));
    await user.selectOptions(within(dialog).getByLabelText("Access level"), "SHARE");
    await user.click(within(dialog).getByLabelText(/View once/));
    expect(within(dialog).getByLabelText("Access level")).toBeDisabled();
    expect(within(dialog).getByText(/cannot stop screenshots/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Share" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/vault/credentials/c1/share/")).toBe(true));
    expect(calls.find((c) => c.path === "/vault/credentials/c1/share/")!.body).toEqual({
      grantee: "u-bob", permission: "VIEW", is_view_once: true, expires_at: null,
    });
    expect(await within(dialog).findByText(/Shared with Bob/)).toBeInTheDocument();
  });

  it("revokes from the tree after confirmation, explaining the cascade", async () => {
    const { calls } = mockFetch(routes({ "POST /shares/s1/revoke/": { body: { revoked: 2 } } }));
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Share Prod DB" }));
    await user.click(await screen.findByRole("button", { name: "Revoke access for Bob" }));
    const confirm = (await screen.findAllByRole("dialog")).at(-1)!;
    expect(within(confirm).getByText(/Everyone they shared it with loses access too/)).toBeInTheDocument();
    await user.click(within(confirm).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/shares/s1/revoke/")).toBe(true));
    expect(await screen.findByText(/2 grants including everything delegated/)).toBeInTheDocument();
  });

  it("shows how a grantee got access and hides actions they do not have", async () => {
    mockFetch(routes({
      "GET /vault/credentials/": page([credential({
        access: "shared", permissions: [], owner_name: "Eve",
        sharing: { permission: "VIEW", expires_at: "2026-11-01T00:00:00Z", shared_by: "Eve", view_once: true, consumed: true },
      })]),
    }));
    renderApp("/vault");
    expect(await screen.findByText("Shared by Eve")).toBeInTheDocument();
    expect(screen.getByText("View-once used")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reveal Prod DB" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Share Prod DB" })).not.toBeInTheDocument();
  });

  it("explains a consumed view-once share when the server answers 410", async () => {
    mockFetch(routes({
      "GET /vault/credentials/": page([credential({ access: "shared", permissions: ["COPY", "REVEAL", "VIEW"] })]),
      "POST /vault/credentials/c1/reveal/": { status: 410, body: { error: { code: "view_once_consumed", message: "This view-once share has already been used." } } },
    }));
    renderApp("/vault");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Reveal Prod DB" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already been used");
  });
});

describe("access requests", () => {
  it("requests access with validation, then the owner approves", async () => {
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /auth/csrf/": { status: 204 },
      "GET /policy/": { body: policy },
      "GET /vault/directory/": page([{ id: "c9", title: "Payroll DB", service_name: null, category: "", owner_name: "Owen" }]),
      "POST /access-requests/": { status: 201, body: {} },
    });
    renderApp("/access-requests");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Request access to Payroll DB" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Send request" }));
    expect(await within(dialog).findByText(/Explain why you need access/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.type(within(dialog).getByLabelText("Reason"), "Month-end payroll run");
    await user.click(within(dialog).getByRole("button", { name: "Send request" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/access-requests/" && c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ credential: "c9", permission: "VIEW", duration_hours: 8, reason: "Month-end payroll run" });
    expect(await screen.findByText("Request sent to Owen.")).toBeInTheDocument();
  });

  it("lets the owner approve a pending request for a shorter time", async () => {
    const pending = {
      id: "r1", credential: "c9", credential_title: "Payroll DB", owner_name: "Eve Example", requester_name: "Rita",
      approver_name: null, permission: "VIEW", requested_duration_hours: 8, reason: "Payroll", state: "PENDING",
      expires_at: "2026-10-18T00:00:00Z", decided_at: null, decision_note: "", share: null, created_at: "2026-10-11T00:00:00Z",
    };
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /auth/csrf/": { status: 204 },
      "GET /vault/directory/": page([]),
      "GET /access-requests/": page([pending]),
      "POST /access-requests/r1/approve/": { body: { ...pending, state: "APPROVED" } },
    });
    renderApp("/access-requests");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "To approve" }));
    await user.click(await screen.findByRole("button", { name: "Review request from Rita" }));
    const dialog = await screen.findByRole("dialog");
    const hours = within(dialog).getByLabelText("Grant for (hours)");
    await user.clear(hours);
    await user.type(hours, "4");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/access-requests/r1/approve/")).toBe(true));
    expect(calls.find((c) => c.path === "/access-requests/r1/approve/")!.body).toEqual({ duration_hours: 4 });
  });
});

describe("notifications", () => {
  it("shows the unread count in the navigation and marks everything read", async () => {
    let unread = 3;
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /auth/csrf/": { status: 204 },
      "GET /notifications/unread-count/": () => ({ body: { unread } }),
      "GET /notifications/": page([{ id: "n1", type: "SHARE_CREATED", priority: "NORMAL", title: 'Eve shared "Prod DB" with you', message: "", link: "/vault", is_read: false, read_at: null, created_at: "2026-10-11T00:00:00Z" }]),
      "POST /notifications/read-all/": () => {
        unread = 0;
        return { body: { updated: 3 } };
      },
    });
    renderApp("/notifications");
    expect(await screen.findByRole("link", { name: "Notifications, 3 unread" })).toBeInTheDocument();
    expect(await screen.findByText('Eve shared "Prod DB" with you')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/notifications/read-all/")).toBe(true));
    expect(await screen.findByRole("link", { name: "Notifications, 0 unread" })).toBeInTheDocument();
  });
});
