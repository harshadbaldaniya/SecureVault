import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp, type FetchCall } from "@/tests/utils";
import type { DelegationTree, ReportDefinition } from "@/types/api";

const page = <T,>(results: T[]) => ({ body: { count: results.length, next: null, previous: null, results } });

const CATALOG: ReportDefinition[] = [
  {
    key: "audit",
    title: "Audit trail compliance",
    description: "Who did what, when, from where.",
    columns: [
      { key: "created_at", label: "When" },
      { key: "action", label: "Action" },
      { key: "outcome", label: "Outcome" },
      { key: "actor_email", label: "Actor" },
    ],
    filters: ["action", "date", "department", "device_trust", "resource", "service", "status", "user"],
    statuses: ["DENIED", "FAILURE", "SUCCESS"],
  },
  {
    key: "devices",
    title: "Device access and posture",
    description: "Every device and its trust state.",
    columns: [
      { key: "name", label: "Device" },
      { key: "trust_state", label: "Trust" },
    ],
    filters: ["date", "department", "device_trust", "user"],
    statuses: [],
  },
  {
    key: "shares",
    title: "Access delegation",
    description: "Who shared what with whom.",
    columns: [
      { key: "credential", label: "Credential" },
      { key: "grantee", label: "Grantee" },
      { key: "state", label: "State" },
      { key: "credential_id", label: "Credential id" },
    ],
    filters: ["date", "department", "resource", "service", "share_status", "user"],
    statuses: [],
  },
];

const ROWS: Record<string, Array<Record<string, string>>> = {
  audit: [{ created_at: "2026-10-11T09:00:00Z", action: "REVEAL", outcome: "SUCCESS", actor_email: "eve@acme.test" }],
  devices: [{ name: "Chrome on Windows", trust_state: "TRUSTED" }],
  shares: [{ credential: "Prod DB", grantee: "Bob Builder", state: "ACTIVE", credential_id: "c-1" }],
};

/** Answers like the server: only the requested columns, in the requested order. */
function reportRoute(key: string) {
  return ({ query }: { query: URLSearchParams }) => {
    const definition = CATALOG.find((r) => r.key === key)!;
    const wanted = query.get("columns")?.split(",") ?? definition.columns.map((c) => c.key);
    const columns = wanted.map((k) => definition.columns.find((c) => c.key === k)!);
    const results = ROWS[key]!.map((row) => Object.fromEntries(wanted.map((k) => [k, row[k] ?? null])));
    return { body: { report: key, title: definition.title, columns, count: results.length, page: 1, results } };
  };
}

const TREE: DelegationTree = {
  credential: "c-1",
  credential_title: "Prod DB",
  owner: "Eve Example",
  nodes: [
    { id: "s1", parent_share: null, depth: 1, grantor: "Eve Example", grantee: "Bob Builder", grantee_email: "bob@acme.test", permission: "SHARE", state: "ACTIVE", expires_at: "2026-10-20T00:00:00Z", is_view_once: false, created_at: "2026-10-10T00:00:00Z" },
    { id: "s2", parent_share: "s1", depth: 2, grantor: "Bob Builder", grantee: "Carol Coder", grantee_email: "carol@acme.test", permission: "VIEW", state: "REVOKED", expires_at: "2026-10-20T00:00:00Z", is_view_once: false, created_at: "2026-10-10T01:00:00Z" },
  ],
};

function setup(role: "SEC_ADMIN" | "ORG_ADMIN" = "SEC_ADMIN") {
  return mockFetch({
    "GET /auth/me/": { body: makeMe(role) },
    "GET /reports/": { body: { reports: CATALOG } },
    "GET /departments/": page([{ id: "dep-1", name: "Engineering", code: "ENG", head: null, head_name: null, status: "ACTIVE", employee_count: 3 }]),
    "GET /services/": page([{ id: "svc-1", name: "AWS", category: "CLOUD", base_url: "", icon_url: "", default_port: null, status: "ACTIVE" }]),
    "GET /reports/audit/": reportRoute("audit"),
    "GET /reports/devices/": reportRoute("devices"),
    "GET /reports/shares/": reportRoute("shares"),
    "GET /shares/tree/c-1/": { body: TREE },
  });
}

const lastReportCall = (calls: FetchCall[], key: string) => calls.filter((c) => c.method === "GET" && c.path === `/reports/${key}/`).at(-1);

describe("reports", () => {
  it("runs the audit report and sends only the filters that report supports", async () => {
    const user = userEvent.setup();
    const { calls } = setup();
    renderApp("/reports");
    expect(await screen.findByText("eve@acme.test")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Audit trail compliance" })).toHaveAttribute("aria-selected", "true");

    await screen.findByRole("option", { name: "Engineering" });
    await user.selectOptions(screen.getByLabelText("Department"), "Engineering");
    await user.click(screen.getByLabelText("REVEAL"));
    await user.click(screen.getByLabelText("COPY"));
    await user.selectOptions(screen.getByLabelText("Status"), "DENIED");
    await waitFor(() => expect(lastReportCall(calls, "audit")?.query.getAll("action")).toEqual(["REVEAL", "COPY"]));
    const audit = lastReportCall(calls, "audit")!.query;
    expect(audit.get("department")).toBe("dep-1");
    expect(audit.get("status")).toBe("DENIED");
    expect(audit.get("page")).toBe("1");

    // Another report: its own filter set, and nothing carried over from the previous one.
    await user.click(screen.getByRole("tab", { name: "Device access and posture" }));
    expect(await screen.findByText("Chrome on Windows")).toBeInTheDocument();
    expect(screen.getByLabelText("Device trust")).toBeInTheDocument();
    expect(screen.queryByLabelText("REVEAL")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Service")).not.toBeInTheDocument();
    const devices = lastReportCall(calls, "devices")!.query;
    expect([...devices.keys()].sort()).toEqual(["page", "page_size"]);
  });

  it("builds a custom column set and exports exactly what is on screen", async () => {
    const user = userEvent.setup();
    const { calls } = setup();
    renderApp("/reports");
    await screen.findByText("eve@acme.test");

    await user.click(screen.getByLabelText("Outcome"));
    await waitFor(() => expect(lastReportCall(calls, "audit")?.query.get("columns")).toBe("created_at,action,actor_email"));
    const table = await screen.findByRole("table", { name: "Audit trail compliance" });
    await waitFor(() => expect(within(table).queryByRole("columnheader", { name: "Outcome" })).not.toBeInTheDocument());
    expect(within(table).getByRole("columnheader", { name: "Actor" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Department"), "Engineering");
    for (const [name, format] of [["CSV", "csv"], ["Excel", "xlsx"], ["PDF", "pdf"]]) {
      const href = screen.getByRole("link", { name }).getAttribute("href")!;
      const url = new URL(href, "http://localhost");
      expect(url.pathname).toBe("/api/v1/reports/audit/");
      expect(url.searchParams.get("format")).toBe(format);
      expect(url.searchParams.get("department")).toBe("dep-1");
      expect(url.searchParams.get("columns")).toBe("created_at,action,actor_email");
    }
  });

  it("opens the delegation tree from the access delegation report", async () => {
    const user = userEvent.setup();
    setup("ORG_ADMIN");
    renderApp("/reports");
    await user.click(await screen.findByRole("tab", { name: "Access delegation" }));
    expect(await screen.findByLabelText("Share status")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "View tree" }));
    const dialog = await screen.findByRole("dialog", { name: "Delegation tree: Prod DB" });
    const tree = await within(dialog).findByRole("tree", { name: "Delegation tree" });
    expect(within(tree).getByText("Bob Builder")).toBeInTheDocument();
    expect(within(tree).getByText("Carol Coder")).toBeInTheDocument();
    expect(within(tree).getByText("revoked")).toBeInTheDocument();
    // Read-only here: revoking happens from the sharing screens.
    expect(within(dialog).queryByRole("button", { name: /Revoke/ })).not.toBeInTheDocument();
  });

  it("is not available to employees", async () => {
    const { calls } = mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/reports");
    expect(await screen.findByRole("heading", { name: "You do not have access to this page" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reports" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith("/reports"))).toBe(false);
  });
});
