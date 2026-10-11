import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FakeWebSocket } from "@/tests/fakeWebSocket";
import { DEFAULT_POLICY, makeMe, mockFetch, renderApp, THIS_DEVICE } from "@/tests/utils";
import type { ActiveLockdown } from "@/types/api";

const page = <T,>(results: T[]) => ({ body: { count: results.length, next: null, previous: null, results } });
const LOCKDOWN: ActiveLockdown = { id: "l1", scope: "GLOBAL", target_user_id: null, triggered_at: "2026-10-11T10:00:00Z", is_active: true };

async function connectedSocket() {
  await waitFor(() => expect(FakeWebSocket.latest()).toBeDefined());
  const socket = FakeWebSocket.latest()!;
  act(() => socket.open());
  return socket;
}

describe("real-time events", () => {
  afterEach(() => vi.useRealTimers());

  it("connects to the events endpoint and shows pushed notifications", async () => {
    let unreadCalls = 0;
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /notifications/unread-count/": () => {
        unreadCalls += 1;
        return { body: { unread: unreadCalls > 1 ? 1 : 0 } };
      },
    });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const socket = await connectedSocket();
    expect(socket.url).toMatch(/^ws:\/\/[^/]+\/ws\/events\/$/);

    act(() => socket.emit({ type: "notification", notification: { title: 'Eve shared "DB" with you', message: "", priority: "NORMAL", link: "/vault" } }));
    expect(await screen.findByText('Eve shared "DB" with you')).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Notifications, 1 unread" })).toBeInTheDocument(); // count refetched
  });

  it("returns to sign-in with an explanation when the server closes the socket for a lockdown", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const socket = await connectedSocket();
    act(() => socket.serverClose(4423));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText(/emergency lockdown/)).toBeInTheDocument();
  });

  it("returns to sign-in when the server ends the session", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const socket = await connectedSocket();
    act(() => socket.serverClose(4401));
    expect(await screen.findByText(/Your session ended/)).toBeInTheDocument();
  });

  it("reconnects with backoff after an unexpected disconnect", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const socket = await connectedSocket();
    act(() => socket.serverClose(1006));
    expect(FakeWebSocket.instances).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("refreshes the lockdown state on a lockdown event and shows administrators a banner", async () => {
    let lockedDown = false;
    mockFetch({ "GET /auth/me/": () => ({ body: makeMe("SEC_ADMIN", { lockdown: lockedDown ? LOCKDOWN : null }) }) });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const socket = await connectedSocket();
    lockedDown = true;
    act(() => socket.emit({ type: "lockdown.activated", lockdown: LOCKDOWN }));
    expect(await screen.findByText("Emergency lockdown active")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage lockdown" })).toBeInTheDocument();
  });

  it("shows a blocking screen to an employee covered by a lockdown", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE", { lockdown: LOCKDOWN }) }, "POST /auth/logout/": { status: 204 } });
    renderApp("/vault");
    expect(await screen.findByRole("heading", { name: "Emergency lockdown in effect" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });
});

describe("device trust", () => {
  it("registers this browser on sign-in with a hex fingerprint and warns when the device is not yet trusted", async () => {
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /policy/": { body: { ...DEFAULT_POLICY, require_device_trust: true } },
    });
    renderApp("/");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/devices/register/")).toBe(true));
    const body = calls.find((c) => c.path === "/devices/register/")!.body as { fingerprint: string };
    expect(body.fingerprint).toMatch(/^([0-9a-f]{64})?$/);
    expect(await screen.findByText(/requires a trusted device/)).toBeInTheDocument();
  });

  it("does not warn when device trust is not required", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    expect(screen.queryByText(/requires a trusted device/)).not.toBeInTheDocument();
  });

  it("lets a device administrator approve someone else's device with a reason", async () => {
    const pending = { ...THIS_DEVICE, id: "d-9", user: "u-9", user_name: "Bob", user_email: "bob@x.test", is_current: false };
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("SEC_ADMIN") },
      "GET /devices/": page([pending]),
      "POST /devices/d-9/approve/": { body: { ...pending, trust_state: "TRUSTED" } },
    });
    renderApp("/devices");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "All devices" }));
    await user.click(await screen.findByRole("button", { name: `Approve ${pending.name}` }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Reason/), "Confirmed by phone");
    await user.click(within(dialog).getByRole("button", { name: "Approve (trust)" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/devices/d-9/approve/")).toBe(true));
    expect(calls.find((c) => c.path === "/devices/d-9/approve/")!.body).toEqual({ reason: "Confirmed by phone" });
    expect(await screen.findByText(/is now trusted/)).toBeInTheDocument();
  });

  it("never offers approval of one's own device", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("SEC_ADMIN") }, "GET /devices/": page([THIS_DEVICE]) });
    renderApp("/devices");
    expect(await screen.findByText("This device")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: `Approve ${THIS_DEVICE.name}` })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Revoke ${THIS_DEVICE.name}` })).toBeInTheDocument();
  });
});

describe("lockdown controls", () => {
  it("validates, asks for confirmation, then activates with re-authentication", async () => {
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("SEC_ADMIN") },
      "GET /lockdown/": page([]),
      "POST /lockdown/activate/": { status: 201, body: { id: "l1", scope: "GLOBAL", terminated_session_count: 12 } },
    });
    renderApp("/lockdown");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Activate lockdown…" }));
    expect(await screen.findByText(/Describe the incident/)).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Reason"), "Leaked deploy key in public repo");
    await user.type(screen.getByLabelText("Your password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Activate lockdown…" }));
    const confirm = await screen.findByRole("dialog");
    expect(within(confirm).getByText(/nobody, including administrators/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/lockdown/activate/")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Lock down now" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/lockdown/activate/")).toBe(true));
    expect(calls.find((c) => c.path === "/lockdown/activate/")!.body).toEqual({
      scope: "GLOBAL", target_user: null, reason: "Leaked deploy key in public repo", password: "correct-horse-battery", code: "",
    });
    expect(await screen.findByText(/12 session\(s\) were terminated/)).toBeInTheDocument();
    expect(screen.getByLabelText("Your password")).toHaveValue(""); // the password is not kept around
  });

  it("is not reachable for employees", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/lockdown");
    expect(await screen.findByText("You do not have access to this page")).toBeInTheDocument();
  });
});

describe("security alerts", () => {
  it("dismisses an alert with a review note", async () => {
    const alert = {
      id: "a1", type: "REVEAL_BURST", severity: "HIGH", status: "OPEN", summary: "Bob revealed 25 secrets in 10 minutes.",
      details: {}, user: "u-9", user_name: "Bob", device: null, device_name: null, ip_address: "10.0.0.5",
      reviewed_by_name: null, reviewed_at: null, review_note: "", created_at: "2026-10-11T10:00:00Z",
    };
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("SEC_ADMIN") },
      "GET /alerts/": page([alert]),
      "POST /alerts/a1/dismiss/": { body: { ...alert, status: "DISMISSED" } },
    });
    renderApp("/alerts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: `Dismiss: ${alert.summary}` }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Review note/), "Scheduled rotation job");
    await user.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/alerts/a1/dismiss/")).toBe(true));
    expect(calls.find((c) => c.path === "/alerts/a1/dismiss/")!.body).toEqual({ note: "Scheduled rotation job" });
  });
});
