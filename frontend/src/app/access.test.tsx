import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp } from "@/tests/utils";

const emptyPage = { body: { count: 0, next: null, previous: null, results: [] } };

describe("role-based screens (UI only; the API enforces the real rules)", () => {
  it("hides admin navigation from employees", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toHaveTextContent("Departments");
    expect(nav).not.toHaveTextContent("Employees");
    expect(nav).not.toHaveTextContent("Audit log");
  });

  it("shows the audit log link to security administrators but not employee management actions", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("SEC_ADMIN") } });
    renderApp("/");
    await screen.findByRole("heading", { name: /Welcome/ });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toHaveTextContent("Audit log");
    expect(nav).toHaveTextContent("Employees");
  });

  it("shows a 403 page, without calling the API, when an employee opens the audit log URL", async () => {
    const { calls } = mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/audit");
    expect(await screen.findByText("You do not have access to this page")).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith("/audit-logs"))).toBe(false);
  });

  it("shows a 403 page for employees on the employee directory", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") } });
    renderApp("/employees");
    expect(await screen.findByText("You do not have access to this page")).toBeInTheDocument();
  });

  it("hides create/edit controls on departments for non-managers but still lists them", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /departments/": { body: { count: 1, next: null, previous: null, results: [{ id: "d1", name: "Engineering", code: "ENG", head: null, head_name: null, status: "ACTIVE", employee_count: 3 }] } },
    });
    renderApp("/departments");
    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New department" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit Engineering/ })).not.toBeInTheDocument();
  });

  it("shows create/edit controls to organization administrators", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("ORG_ADMIN") },
      "GET /departments/": { body: { count: 1, next: null, previous: null, results: [{ id: "d1", name: "Engineering", code: "ENG", head: null, head_name: null, status: "ACTIVE", employee_count: 3 }] } },
    });
    renderApp("/departments");
    expect(await screen.findByRole("button", { name: "New department" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Edit Engineering" })).toBeInTheDocument();
  });

  it("forces users whose policy requires MFA onto the security page", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE", { mfa_enrollment_required: true }) } });
    renderApp("/departments");
    expect(await screen.findByRole("heading", { name: "Account security" })).toBeInTheDocument();
    expect(screen.getByText(/requires two-step verification/)).toBeInTheDocument();
  });

  it("shows an empty state instead of a blank table", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("ORG_ADMIN") }, "GET /departments/": emptyPage });
    renderApp("/departments");
    expect(await screen.findByText("No departments yet")).toBeInTheDocument();
  });

  it("shows a clear error when the list cannot be loaded", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("ORG_ADMIN") },
      "GET /departments/": { status: 500, body: { error: { code: "server_error", message: "Internal server error." } } },
    });
    renderApp("/departments");
    expect(await screen.findByRole("alert")).toHaveTextContent("Internal server error.");
  });

  it("shows the policy as read-only for employees", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /policy/": { body: { id: "p", name: "Default", min_password_length: 14, require_uppercase: true, require_numbers: true, require_symbols: true, max_password_age_days: 90, expiry_warning_days: 14, allow_view_once: true, max_share_duration_days: 30, require_device_trust: false, require_mfa: false, updated_at: "2026-10-11T00:00:00Z" } },
    });
    renderApp("/policy");
    expect(await screen.findByText(/only administrators can change it/)).toBeInTheDocument();
    expect(screen.getByLabelText("Minimum length")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save policy" })).not.toBeInTheDocument();
  });
});
