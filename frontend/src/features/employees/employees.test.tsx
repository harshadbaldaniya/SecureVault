import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp } from "@/tests/utils";
import type { Employee } from "@/types/api";

const ERIN: Employee = {
  id: "u-2",
  email: "erin@acme.test",
  full_name: "Erin Example",
  role: "EMPLOYEE",
  status: "ACTIVE",
  department: null,
  department_name: null,
  last_login: null,
  created_at: "2026-10-01T10:00:00Z",
};
const page = (results: Employee[]) => ({ body: { count: results.length, next: null, previous: null, results } });

describe("employee directory actions", () => {
  it("names the two-step reset button so that its visible text is part of the accessible name", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("ORG_ADMIN") }, "GET /users/": page([ERIN]) });
    renderApp("/employees");
    const button = await screen.findByRole("button", { name: /^Reset MFA/ });
    expect(button).toHaveTextContent("Reset MFA");
    expect(button).toHaveAccessibleName("Reset MFA (two-step verification) for Erin Example");
  });

  it("asks before resetting two-step verification, and Cancel changes nothing on the server", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("ORG_ADMIN") },
      "GET /users/": page([ERIN]),
      "POST /users/u-2/reset-mfa/": { status: 204 },
    });
    renderApp("/employees");
    await user.click(await screen.findByRole("button", { name: /^Reset MFA/ }));
    const dialog = screen.getByRole("dialog", { name: "Reset two-step verification" });
    expect(within(dialog).queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument(); // a question: Cancel is the way out
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method === "POST" && c.path.startsWith("/users/"))).toBe(false);

    await user.click(screen.getByRole("button", { name: /^Reset MFA/ }));
    await user.click(within(screen.getByRole("dialog", { name: "Reset two-step verification" })).getByRole("button", { name: "Reset MFA" }));
    await screen.findByRole("table", { name: "Employees" });
    expect(calls.filter((c) => c.method === "POST" && c.path === "/users/u-2/reset-mfa/")).toHaveLength(1);
  });
});
