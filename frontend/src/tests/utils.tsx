import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { makeQueryClient, Providers } from "@/app/providers";
import { AppRoutes } from "@/app/routes";
import type { Me, Permission, Role } from "@/types/api";

type Handler = (request: { method: string; path: string; query: URLSearchParams; body: unknown; headers: Record<string, string> }) => { status?: number; body?: unknown };

/** Route table keyed by "METHOD /path" (query string ignored). Unmatched calls fail the test loudly. */
export type Routes = Record<string, Handler | { status?: number; body?: unknown }>;

export interface FetchCall {
  method: string;
  path: string;
  /** Parsed query string (repeated keys preserved). */
  query: URLSearchParams;
  /** JSON bodies are parsed; anything else (e.g. FormData) is passed through. */
  body: unknown;
  headers: Record<string, string>;
}

export const DEFAULT_POLICY = {
  id: "p", name: "Default", min_password_length: 14, require_uppercase: true, require_numbers: true, require_symbols: true,
  max_password_age_days: 90, expiry_warning_days: 14, allow_view_once: true, max_share_duration_days: 30,
  require_device_trust: false, require_mfa: false, block_on_high_risk: false, updated_at: "2026-10-11T00:00:00Z",
};

export const THIS_DEVICE = {
  id: "d-1", name: "Chrome on Windows", user: "u-1", user_name: "Eve Example", user_email: "eve@acme.test", os: "Windows",
  browser: "Chrome", trust_state: "PENDING", first_ip: "127.0.0.1", last_ip: "127.0.0.1", last_seen_at: "2026-10-11T00:00:00Z",
  trust_changed_by_name: null, trust_changed_at: null, trust_reason: "", is_current: true, created_at: "2026-10-11T00:00:00Z",
};

export const EMPTY_DASHBOARD = {
  me: {
    credentials: 0, shared_with_me: 0, shares_given: 0, requests_to_approve: 0, my_pending_requests: 0, expiring_soon: 0,
    expired: 0, weak: 0, reused: 0, strength: [], devices: { trusted: 0, not_trusted: 0 }, unread_notifications: 0, activity: [],
  },
  organization: null,
};

/** Endpoints every signed-in page calls; tests may override them. */
const DEFAULT_ROUTES: Routes = {
  "GET /dashboard/": { body: EMPTY_DASHBOARD },
  "GET /notifications/unread-count/": { body: { unread: 0 } },
  "POST /devices/register/": { body: THIS_DEVICE },
  "GET /policy/": { body: DEFAULT_POLICY },
  "GET /auth/csrf/": { status: 204 },
};

export function mockFetch(overrides: Routes) {
  const routes: Routes = { ...DEFAULT_ROUTES, ...overrides };
  const calls: FetchCall[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const headers = Object.fromEntries(Object.entries((init?.headers as Record<string, string>) ?? {}));
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    calls.push({ method, path, query: url.searchParams, body, headers });

    const entry = routes[`${method} ${path}`];
    if (!entry) throw new Error(`Unmocked request: ${method} ${path}`);
    const result = typeof entry === "function" ? entry({ method, path, query: url.searchParams, body, headers }) : entry;
    const status = result.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}

const SECURITY_OPERATIONS: Permission[] = [
  "audit.view", "shares.revoke_any", "shares.view_all", "devices.manage", "alerts.manage", "lockdown.manage", "reports.view",
];

export const ALL_ADMIN_PERMISSIONS: Permission[] = [
  "users.view", "users.manage", "invitations.manage", "departments.manage", "services.manage", "policies.manage",
  ...SECURITY_OPERATIONS,
];

const PERMISSIONS: Record<Role, Permission[]> = {
  ORG_ADMIN: ALL_ADMIN_PERMISSIONS,
  SEC_ADMIN: ["users.view", "policies.manage", ...SECURITY_OPERATIONS],
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
    lockdown: null,
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
