import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch, renderApp, unauthenticated } from "@/tests/utils";

const STRONG = "Brand-New-Passphrase-77";

function setHash(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
}

describe("one-time token pages", () => {
  it("reads the invitation token from the URL fragment, removes it from the address bar and submits it", async () => {
    setHash("#token=abc123");
    const { calls } = mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/invitations/accept/": { body: { detail: "ok" } },
    });
    renderApp("/accept-invite");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("New password"), STRONG);
    await user.type(screen.getByLabelText("Confirm new password"), STRONG);
    await user.click(screen.getByRole("button", { name: "Activate account" }));

    expect(await screen.findByText(/Account activated/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/auth/invitations/accept/")?.body).toEqual({ token: "abc123", password: STRONG });
    expect(window.location.hash).toBe("");
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("explains a missing token instead of showing a form", async () => {
    setHash("");
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/reset-password");
    expect(await screen.findByText(/missing or incomplete/)).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("blocks mismatched passwords locally", async () => {
    setHash("#token=abc123");
    const { calls } = mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/reset-password");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("New password"), STRONG);
    await user.type(screen.getByLabelText("Confirm new password"), "Something-Else-123");
    await user.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("password-reset"))).toBe(false);
  });

  it("shows the server's password-strength feedback and keeps the form for another try", async () => {
    setHash("#token=abc123");
    mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/password-reset/confirm/": { status: 400, body: { error: { code: "weak_password", message: "Password does not meet the requirements.", details: { password: ["This password is too common."] } } } },
    });
    renderApp("/reset-password");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("New password"), "password1234");
    await user.type(screen.getByLabelText("Confirm new password"), "password1234");
    await user.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText("This password is too common.")).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
  });

  it("gives the same confirmation for any email on the forgot-password screen", async () => {
    mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/password-reset/": { status: 202, body: { detail: "If an account exists..." } },
    });
    renderApp("/forgot-password");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "nobody@example.test");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/If an account exists for that email/)).toBeInTheDocument();
  });
});
