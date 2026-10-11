import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FakeWebSocket } from "@/tests/fakeWebSocket";
import { makeMe, mockFetch, renderApp } from "@/tests/utils";

import { arrangeToasts } from "./Toasts";

async function connectedSocket() {
  await waitFor(() => expect(FakeWebSocket.latest()).toBeDefined());
  const socket = FakeWebSocket.latest()!;
  act(() => socket.open());
  return socket;
}

const notification = (over: Record<string, unknown> = {}) => ({
  type: "notification",
  notification: { id: "n1", title: 'Eve shared "DB" with you', message: "Open it in the vault.", priority: "NORMAL", link: "/vault", ...over },
});

async function setup(extra: Record<string, unknown> = {}) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const mocked = mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") }, "POST /notifications/n1/read/": { status: 204 }, ...extra });
  renderApp("/");
  await screen.findByRole("heading", { name: /Welcome/ });
  return { ...mocked, socket: await connectedSocket() };
}

const advance = (ms: number) => act(async () => vi.advanceTimersByTimeAsync(ms));
const reads = (calls: { method: string; path: string }[]) => calls.filter((c) => c.method === "POST" && c.path.endsWith("/read/"));

describe("notification toasts", () => {
  afterEach(() => vi.useRealTimers());

  it("an ordinary notification disappears by itself after about five seconds", async () => {
    const { socket, calls } = await setup();
    act(() => socket.emit(notification()));
    expect(await screen.findByText('Eve shared "DB" with you')).toBeInTheDocument();
    await advance(4000);
    expect(screen.getByText('Eve shared "DB" with you')).toBeInTheDocument();
    await advance(1500);
    expect(screen.queryByText('Eve shared "DB" with you')).not.toBeInTheDocument();
    // Timing out is not "read": the stored notification is untouched.
    expect(reads(calls)).toHaveLength(0);
  });

  it("pauses while the pointer is over it or focus is inside, then resumes with the time that is left", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { socket } = await setup();
    act(() => socket.emit(notification()));
    const text = await screen.findByText('Eve shared "DB" with you');
    await advance(3000);
    await user.hover(text);
    await advance(10_000);
    expect(screen.getByText('Eve shared "DB" with you')).toBeInTheDocument();
    await user.unhover(text);
    await advance(1500); // 3000 used + 1500 < 5000: still there
    expect(screen.getByText('Eve shared "DB" with you')).toBeInTheDocument();
    await advance(1000);
    expect(screen.queryByText('Eve shared "DB" with you')).not.toBeInTheDocument();

    act(() => socket.emit(notification({ id: "n2", title: "Second" })));
    await screen.findByText("Second");
    act(() => screen.getByRole("link", { name: "Open" }).focus());
    await advance(10_000);
    expect(screen.getByText("Second")).toBeInTheDocument(); // keyboard focus pauses it too
  });

  it("keeps high-priority security warnings until the user dismisses them", async () => {
    const { socket } = await setup();
    act(() => socket.emit(notification({ id: "n3", title: 'New device registered: "Edge"', priority: "HIGH", link: "/devices" })));
    await screen.findByText('New device registered: "Edge"');
    await advance(60_000);
    expect(screen.getByText('New device registered: "Edge"')).toBeInTheDocument();
  });

  it("dismissing hides the toast without touching the stored notification, and it does not come back when delivered again", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { socket, calls } = await setup();
    act(() => socket.emit(notification({ priority: "HIGH" })));
    await user.click(await screen.findByRole("button", { name: /^Dismiss: / }));
    expect(screen.queryByText('Eve shared "DB" with you')).not.toBeInTheDocument();
    expect(reads(calls)).toHaveLength(0);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    act(() => socket.emit(notification({ priority: "HIGH" }))); // same id, e.g. after a reconnect
    expect(screen.queryByText('Eve shared "DB" with you')).not.toBeInTheDocument();
  });

  it("Open goes to the destination, removes the toast and marks that notification read", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { socket, calls } = await setup({ "GET /vault/credentials/": { body: { count: 0, next: null, previous: null, results: [] } } });
    act(() => socket.emit(notification({ priority: "HIGH" })));
    await user.click(await screen.findByRole("link", { name: "Open" }));
    expect(await screen.findByRole("heading", { name: "Credentials" })).toBeInTheDocument();
    expect(screen.queryByText('Eve shared "DB" with you')).not.toBeInTheDocument();
    await waitFor(() => expect(reads(calls).map((c) => c.path)).toEqual(["/notifications/n1/read/"]));
  });

  it("shows two cards at most, summarises the rest, and never hides a critical warning", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { socket } = await setup();
    for (const n of [1, 2, 3, 4]) act(() => socket.emit(notification({ id: `m${n}`, title: `Notice ${n}`, priority: "HIGH", link: "" })));
    const region = await screen.findByRole("region", { name: "New notifications" });
    expect(within(region).getAllByRole("button", { name: /^Dismiss: / })).toHaveLength(2);
    expect(within(region).getByText("Notice 4")).toBeInTheDocument(); // newest first among equals
    expect(within(region).getByText("Notice 3")).toBeInTheDocument();
    expect(within(region).queryByText("Notice 1")).not.toBeInTheDocument();
    expect(within(region).getByText(/\+2 more notifications/)).toHaveTextContent("(2 high priority)");
    expect(within(region).getByRole("link", { name: "View all" })).toHaveAttribute("href", "/notifications");

    // A critical warning takes a card even when the stack is full.
    act(() => socket.emit(notification({ id: "c1", title: "Critical thing", priority: "CRITICAL", link: "" })));
    expect(within(region).getByText("Critical thing")).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Dismiss: Critical thing" }));
    expect(within(region).queryByText("Critical thing")).not.toBeInTheDocument();
  });

  it("ordinary notices that do not get a card stop being counted after a few seconds", async () => {
    const { socket } = await setup();
    act(() => socket.emit(notification({ id: "h1", title: "Warning", priority: "HIGH", link: "" })));
    act(() => socket.emit(notification({ id: "h2", title: "Warning 2", priority: "HIGH", link: "" })));
    for (const n of [1, 2]) act(() => socket.emit(notification({ id: `o${n}`, title: `Ordinary ${n}`, priority: "NORMAL", link: "" })));
    const region = await screen.findByRole("region", { name: "New notifications" });
    expect(within(region).getByText(/\+2 more notifications/)).toBeInTheDocument();
    await advance(5500);
    expect(within(region).queryByText(/more notification/)).not.toBeInTheDocument();
    expect(within(region).getByText("Warning")).toBeInTheDocument(); // the warnings are still there
  });

  it("arrangeToasts ranks by priority, then newest, and gives every CRITICAL warning a slot", () => {
    const t = (key: string, priority: "LOW" | "NORMAL" | "HIGH" | "CRITICAL") => ({ key, title: key, message: "", link: "", priority });
    const { shown, hidden } = arrangeToasts([t("a", "NORMAL"), t("b", "HIGH"), t("c", "LOW"), t("d", "NORMAL")]);
    expect(shown.map((x) => x.key)).toEqual(["b", "d"]);
    expect(hidden.map((x) => x.key)).toEqual(["a", "c"]);
    const crit = arrangeToasts([t("1", "CRITICAL"), t("2", "CRITICAL"), t("3", "CRITICAL"), t("4", "HIGH")]);
    expect(crit.shown.map((x) => x.key)).toEqual(["1", "2", "3"]);
    expect(crit.hidden.map((x) => x.key)).toEqual(["4"]);
  });
});

describe("notifications page", () => {
  const unread = { id: "n9", type: "SHARE", priority: "NORMAL", title: "Eve shared a key", message: "", link: "", is_read: false, read_at: null, created_at: "2026-10-11T10:00:00Z" };

  it("keeps a notification unread and says so when marking it read fails", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /notifications/": { body: { count: 1, next: null, previous: null, results: [unread] } },
      "POST /notifications/n9/read/": { status: 500, body: { error: { code: "server_error", message: "Something went wrong on our side." } } },
    });
    renderApp("/notifications");
    await user.click(await screen.findByRole("button", { name: "Mark read: Eve shared a key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong on our side.");
    expect(screen.getByRole("button", { name: "Mark read: Eve shared a key" })).toBeInTheDocument();
  });

  it("names the bell naturally, keeps the visible label in the name and follows the count", async () => {
    let count = 14;
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") }, "GET /notifications/unread-count/": () => ({ body: { unread: count } }) });
    renderApp("/");
    const bell = await screen.findByRole("link", { name: "Notifications, 14 unread" });
    expect(bell).toHaveTextContent("Notifications");
    count = 0;
    await act(async () => {
      FakeWebSocket.latest()?.open();
      FakeWebSocket.latest()?.emit({ type: "notification", notification: { id: "z", title: "x", message: "", priority: "NORMAL", link: "" } });
    });
    expect(await screen.findByRole("link", { name: "Notifications" })).toBeInTheDocument();
  });
});
