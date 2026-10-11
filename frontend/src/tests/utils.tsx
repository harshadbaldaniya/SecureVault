import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { makeQueryClient, Providers } from "@/app/providers";
import { AppRoutes } from "@/app/routes";
import type { Me, Permission, Role } from "@/types/api";

type Handler = (request: { method: string; path: string; body: unknown; headers: Record<string, string> }) => { status?: number; body?: unknown };

/** Route table keyed by "METHOD /path" (query string ignored). Unmatched calls fail the test loudly. */
export type Routes = Record<string, Handler | { status?: number; body?: unknown }>;

export interface FetchCall {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
}

export function mockFetch(routes: Routes) {
  const calls: FetchCall[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const headers = Object.fromEntries(Object.entries((init?.headers as Record<string, string>) ?? {}));
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, headers });

    const entry = routes[`${method} ${path}`];
    if (!entry) throw new Error(`Unmocked request: ${method} ${path}`);
    const result = typeof entry === "function" ? entry({ method, path, body, headers }) : entry;
    const status = result.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}

export const ALL_ADMIN_PERMISSIONS: Permission[] = [
  "users.view", "users.manage", "invitations.manage", "departments.manage", "services.manage", "policies.manage", "audit.view",
];

const PERMISSIONS: Record<Role, Permission[]> = {
  ORG_ADMIN: ALL_ADMIN_PERMISSIONS,
  SEC_ADMIN: ["users.view", "policies.manage", "audit.view"],
  EMPLOYEE: [],
};

export function makeMe(role: Role = "EMPLOYEE", overrides: Partial<Me> = {}): Me {
  return {
    id: "u-1",
    email: "eve@acme.test",
    full_name: "Eve Example",
    role,
    status: "ACTIVE",
    organization: { id: "o-1", name: "Acme", slug: "acme" },
    department: null,
    permissions: PERMISSIONS[role],
    mfa_enabled: false,
    mfa_enrollment_required: false,
    ...overrides,
  };
}

export const unauthenticated = { status: 401, body: { error: { code: "not_authenticated", message: "Authentication credentials were not provided." } } };

export function renderApp(path = "/") {
  const client = makeQueryClient({ retry: false });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}
