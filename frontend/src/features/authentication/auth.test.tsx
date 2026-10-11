import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp, unauthenticated } from "@/tests/utils";

const invalidCredentials = { status: 400, body: { error: { code: "invalid_credentials", message: "Invalid email or password." } } };

describe("sign-in", () => {
  it("redirects anonymous visitors from protected pages to the login screen", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/departments");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the server's generic error and does not reveal which part was wrong", async () => {
    mockFetch({ "GET /auth/me/": unauthenticated, "POST /auth/login/": invalidCredentials, "GET /auth/csrf/": { status: 204 } });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "eve@acme.test");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });

  it("validates fields before calling the server", async () => {
    const { calls } = mockFetch({ "GET /auth/me/": unauthenticated });
    renderApp("/login");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email.")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/auth/login/")).toBe(false);
  });

  it("signs in without MFA and lands on the home page", async () => {
    const me = makeMe("EMPLOYEE");
    mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/login/": { body: { mfa_required: false, user: me } },
    });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), me.email);
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: /Welcome, Eve Example/ })).toBeInTheDocument();
  });

  it("requires the second factor before the app is shown", async () => {
    const me = makeMe("ORG_ADMIN", { mfa_enabled: true });
    const { calls } = mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/login/": { body: { mfa_required: true, user: null } },
      "POST /auth/mfa/verify/": { body: { mfa_required: false, user: me } },
    });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), me.email);
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Two-step verification" })).toBeInTheDocument();
    expect(screen.queryByText(/Welcome/)).not.toBeInTheDocument();
    // Regression: the code field must not inherit the previous step's input (the email address).
    expect(screen.getByLabelText("Verification code")).toHaveValue("");

    await user.type(screen.getByLabelText("Verification code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: /Welcome/ })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/auth/mfa/verify/")?.body).toEqual({ code: "123456" });
  });

  it("returns to the password step when the pending sign-in expires", async () => {
    mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/login/": { body: { mfa_required: true, user: null } },
      "POST /auth/mfa/verify/": { status: 400, body: { error: { code: "mfa_session_expired", message: "Your sign-in attempt expired. Sign in again." } } },
    });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@b.test");
    await user.type(screen.getByLabelText("Password"), "pw-pw-pw-pw-pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.type(await screen.findByLabelText("Verification code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("expired");
  });

  it("stores nothing in local or session storage during sign-in", async () => {
    const me = makeMe("EMPLOYEE");
    mockFetch({
      "GET /auth/me/": unauthenticated,
      "GET /auth/csrf/": { status: 204 },
      "POST /auth/login/": { body: { mfa_required: false, user: me } },
    });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), me.email);
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: /Welcome/ });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe("signed-in navigation", () => {
  it("signs out and returns to the login screen", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") }, "GET /auth/csrf/": { status: 204 }, "POST /auth/logout/": { status: 204 } });
    renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("still signs out locally when the logout request fails", async () => {
    mockFetch({ "GET /auth/me/": { body: makeMe("EMPLOYEE") }, "GET /auth/csrf/": { status: 204 }, "POST /auth/logout/": { status: 500, body: {} } });
    renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("sends users to the login screen when the session expires mid-use", async () => {
    let signedIn = true;
    mockFetch({
      "GET /auth/me/": () => (signedIn ? { body: makeMe("ORG_ADMIN") } : unauthenticated),
      "GET /departments/": () => (signedIn ? { body: { count: 0, next: null, previous: null, results: [] } } : unauthenticated),
      "GET /services/": () => (signedIn ? { body: { count: 0, next: null, previous: null, results: [] } } : unauthenticated),
    });
    renderApp("/departments");
    await screen.findByRole("heading", { name: "Departments" });
    signedIn = false; // e.g. an administrator suspended this account or a lockdown ended the session
    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "Service catalog" })); // this request now gets 401
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument());
  });
});
