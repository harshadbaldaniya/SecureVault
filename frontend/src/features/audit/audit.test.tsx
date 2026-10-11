import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp } from "@/tests/utils";
import type { AuditEntry } from "@/types/api";

const entry = (id: number, over: Partial<AuditEntry> = {}): AuditEntry => ({
  id,
  sequence: id,
  created_at: "2026-10-12T01:26:00Z",
  action: "LOGIN",
  outcome: "SUCCESS",
  actor_id: "u-1",
  actor_email: "admin@securevault.test",
  target_type: "user",
  target_id: "u-1",
  target_label: "admin@securevault.test",
  reason: "",
  metadata: {},
  ip_address: "172.18.0.1",
  request_id: `req-${id}-aaaa-bbbb-cccc`,
  ...over,
});
const ENTRIES = [entry(77), entry(76, { action: "REVEAL", reason: "device_untrusted", metadata: { purpose: "view", depth: 0 } })];

async function setup() {
  const user = userEvent.setup();
  mockFetch({
    "GET /auth/me/": { body: makeMe("SEC_ADMIN") },
    "GET /audit-logs/": { body: { count: 2, next: null, previous: null, results: ENTRIES } },
  });
  renderApp("/audit");
  await screen.findByRole("table", { name: "Audit log" });
  return user;
}
const show = (n: number) => screen.getByRole("button", { name: new RegExp(`(Show|Hide) details for record #${n}$`) });

describe("audit record details panel", () => {
  it("opens beside the record as a labelled panel without touching the table", async () => {
    const user = await setup();
    const table = screen.getByRole("table", { name: "Audit log" });
    const shape = () => {
      const row = within(table).getAllByRole("row")[1]!;
      return { cells: row.querySelectorAll("td").length, text: row.textContent!.replace(/Show|Hide/g, ""), blocks: row.querySelectorAll("dl, pre").length };
    };
    const rowBefore = shape();

    expect(show(77)).toHaveTextContent("Show");
    await user.click(show(77));

    const panel = screen.getByRole("dialog", { name: "Record #77 — LOGIN" });
    expect(within(panel).getByText("Audit Record Details")).toBeInTheDocument();
    expect(within(panel).getByText("req-77-aaaa-bbbb-cccc")).toBeInTheDocument();
    expect(within(panel).getByText("SUCCESS")).toBeInTheDocument();
    // Floating: it lives outside the table, and the row itself is exactly as it was apart from the button label.
    expect(table).not.toContainElement(panel);
    expect(within(table).queryByText("req-77-aaaa-bbbb-cccc")).not.toBeInTheDocument();
    expect(shape()).toEqual(rowBefore);
    expect(show(77)).toHaveTextContent("Hide");
    expect(show(77)).toHaveAttribute("aria-expanded", "true");
    expect(show(77)).toHaveAttribute("aria-controls", panel.id);
    expect(within(panel).getByRole("button", { name: "Close audit record details" })).toHaveFocus();
  });

  it("shows every existing detail: reason, request id and metadata", async () => {
    const user = await setup();
    await user.click(show(76));
    const panel = screen.getByRole("dialog", { name: "Record #76 — REVEAL" });
    expect(within(panel).getByText("device_untrusted")).toBeInTheDocument();
    expect(within(panel).getByText("req-76-aaaa-bbbb-cccc")).toBeInTheDocument();
    expect(panel.querySelector("pre")?.textContent).toContain('"purpose": "view"');
  });

  it("closes with Hide, with the close button, with Escape and on a click outside", async () => {
    const user = await setup();
    const open = async (n = 77) => {
      await user.click(show(n));
      return screen.getByRole("dialog");
    };

    await open();
    await user.click(show(77)); // the button reads Hide now
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(show(77)).toHaveTextContent("Show");

    const panel = await open();
    await user.click(within(panel).getByRole("button", { name: "Close audit record details" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(show(77)).toHaveFocus(); // focus goes back to where the user was

    await open();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(show(77)).toHaveFocus();

    await open();
    await user.click(screen.getByRole("heading", { name: "Audit log" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the panel open when you click inside it", async () => {
    const user = await setup();
    await user.click(show(77));
    await user.click(screen.getByText("Audit Record Details"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("opening another record closes the previous panel", async () => {
    const user = await setup();
    await user.click(show(77));
    await user.click(show(76));
    const panels = screen.getAllByRole("dialog");
    expect(panels).toHaveLength(1);
    expect(panels[0]).toHaveAccessibleName("Record #76 — REVEAL");
    expect(show(77)).toHaveTextContent("Show");
    expect(show(76)).toHaveTextContent("Hide");
  });
});
