import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EMPTY_DASHBOARD, makeMe, mockFetch, renderApp } from "@/tests/utils";
import type { Dashboard } from "@/types/api";

const WEEK = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"];
const activity = (counts: number[]) => WEEK.map((date, i) => ({ date, count: counts[i] ?? 0 }));

const ME: Dashboard["me"] = {
  ...EMPTY_DASHBOARD.me,
  credentials: 12,
  shared_with_me: 3,
  shares_given: 1,
  requests_to_approve: 2,
  my_pending_requests: 1,
  expiring_soon: 4,
  expired: 1,
  weak: 2,
  reused: 1,
  strength: [
    { label: "very_weak", count: 0 },
    { label: "weak", count: 2 },
    { label: "fair", count: 3 },
    { label: "strong", count: 4 },
    { label: "very_strong", count: 3 },
  ],
  activity: activity([0, 2, 5, 1, 0, 0, 3]),
};

const ORGANIZATION: NonNullable<Dashboard["organization"]> = {
  credentials: 40,
  active_shares: 7,
  pending_requests: 2,
  devices: { trusted: 6, pending: 3, suspended: 1 },
  open_alerts: { LOW: 1, MEDIUM: 0, HIGH: 2 },
  active_lockdowns: [{ id: "l1", scope: "USER", target_user_id: "u-9", triggered_at: "2026-10-11T10:00:00Z", is_active: true }],
  recent_security_events: [
    { created_at: "2026-10-11T09:00:00Z", action: "DEVICE_TRUST_CHANGE", outcome: "SUCCESS", actor_email: "sec@acme.test", target_label: "Chrome on Windows", reason: "" },
    { created_at: "2026-10-11T08:00:00Z", action: "REVEAL", outcome: "DENIED", actor_email: "eve@acme.test", target_label: "Prod DB", reason: "device_untrusted" },
  ],
  activity: activity([1, 1, 1, 1, 1, 1, 9]),
};

const tile = (name: string) => screen.getByRole("group", { name });

describe("dashboard", () => {
  it("shows an employee their own numbers and nothing organization-wide", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") }, "GET /dashboard/": { body: { me: ME, organization: null } } });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Your vault" })).toBeInTheDocument();

    expect(within(tile("Your credentials")).getByText("12")).toBeInTheDocument();
    expect(within(tile("Shared with you")).getByText("You share 1 grant")).toBeInTheDocument();
    expect(within(tile("Expiring soon")).getByText("1 already expired")).toBeInTheDocument();
    expect(within(tile("Weak or reused")).getByText("3")).toBeInTheDocument();
    expect(within(tile("Weak or reused")).getByText("2 weak · 1 reused")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Organization security" })).not.toBeInTheDocument();
  });

  it("labels every chart mark and offers the same data as a table", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") }, "GET /dashboard/": { body: { me: ME, organization: null } } });
    renderApp("/");
    const chart = await screen.findByRole("figure", { name: "Your reveals and copies" });

    // One keyboard-reachable, labelled mark per day: the chart never relies on color or hover alone.
    const columns = within(chart).getAllByRole("button", { name: /reveals and copies$/ });
    expect(columns).toHaveLength(7);
    expect(within(chart).getByRole("button", { name: /: 5 reveals and copies$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Strong: 4 credentials" })).toBeInTheDocument();

    // A two-option control (not two text links): the selected view is exposed, not just coloured.
    const view = within(chart).getByRole("group", { name: "Your reveals and copies view" });
    expect(within(view).getByRole("button", { name: "Chart" })).toHaveAttribute("aria-pressed", "true");
    expect(within(view).getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");

    await user.click(within(view).getByRole("button", { name: "Table" }));
    const table = within(chart).getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(8); // header + 7 days
    expect(rows.map((r) => r.lastElementChild?.textContent)).toEqual(["Reveals and copies", "0", "2", "5", "1", "0", "0", "3"]);
    expect(within(view).getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
    expect(within(view).getByRole("button", { name: "Chart" })).toHaveAttribute("aria-pressed", "false");
    await user.click(within(view).getByRole("button", { name: "Chart" }));
    expect(within(chart).queryByRole("table")).not.toBeInTheDocument();
  });

  it("adds the organization overview for security staff", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("SEC_ADMIN") }, "GET /dashboard/": { body: { me: ME, organization: ORGANIZATION } } });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Organization security" })).toBeInTheDocument();

    expect(within(tile("Active share grants")).getByText("7")).toBeInTheDocument();
    // Status is shown with text, not color alone.
    expect(within(tile("Lockdown")).getByText("1 active")).toBeInTheDocument();
    expect(screen.getByText("2 high")).toBeInTheDocument();
    expect(screen.getByText("0 medium")).toBeInTheDocument();

    const meter = screen.getByRole("meter", { name: "Trusted devices" });
    expect(meter).toHaveAttribute("aria-valuenow", "6");
    expect(meter).toHaveAttribute("aria-valuemax", "10");
    expect(screen.getByText("6 of 10 devices (60%)")).toBeInTheDocument();

    const events = screen.getByRole("table", { name: "Recent security events" });
    expect(within(events).getByText("DEVICE_TRUST_CHANGE")).toBeInTheDocument();
    expect(within(events).getByText("denied")).toBeInTheDocument();
    expect(within(events).getByText("Prod DB")).toBeInTheDocument();
  });

  it("keeps the page usable when the dashboard cannot load", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /dashboard/": { status: 500, body: { error: { code: "server_error", message: "Something went wrong on our side." } } },
    });
    renderApp("/");
    expect(await screen.findByText("Something went wrong on our side.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Welcome/ })).toBeInTheDocument();
  });
});
