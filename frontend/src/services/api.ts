/**
 * Minimal API client for the SecureVault backend.
 *
 * - Cookie-session auth: requests use `credentials: "same-origin"`; no token is ever read by JS.
 * - CSRF: the readable `sv_csrftoken` cookie is echoed in `X-CSRFToken` on every write.
 * - Errors: the backend's `{error: {code, message, details}}` envelope becomes an ApiError.
 * - Nothing is cached in local/session storage.
 */

const BASE = "/api/v1";
const CSRF_COOKIE = "sv_csrftoken";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, string[]> | undefined;

  constructor(status: number, code: string, message: string, details?: Record<string, string[]>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Handler = () => void;
let onUnauthorized: Handler | null = null;
let onLockdown: Handler | null = null;

/** The auth provider registers this so any 401 returns the user to the sign-in screen. */
export function setUnauthorizedHandler(handler: Handler | null): void {
  onUnauthorized = handler;
}

/** Called on any 423 (emergency lockdown) so the app can refresh the user's lockdown state. */
export function setLockdownHandler(handler: Handler | null): void {
  onLockdown = handler;
}

function readCookie(name: string): string | null {
  for (const part of document.cookie.split("; ")) {
    const [key, ...rest] = part.split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

async function ensureCsrfCookie(): Promise<string> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing) return existing;
  await fetch(`${BASE}/auth/csrf/`, { credentials: "same-origin" });
  return readCookie(CSRF_COOKIE) ?? "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  /** Do not treat 401 as "session expired" (used by the sign-in calls themselves). */
  skipUnauthorizedHandler?: boolean;
}

function toQuery(params: RequestOptions["params"]): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function toApiError(status: number, payload: unknown): ApiError {
  const envelope = (payload as { error?: { code?: string; message?: string; details?: Record<string, string[]> } })
    ?.error;
  return new ApiError(
    status,
    envelope?.code ?? "error",
    envelope?.message ?? "Something went wrong. Please try again.",
    envelope?.details,
  );
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = await ensureCsrfCookie();

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}${toQuery(options.params)}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection and try again.");
  }

  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (response.status === 401 && !options.skipUnauthorizedHandler) onUnauthorized?.();
    if (response.status === 423) onLockdown?.();
    throw toApiError(response.status, payload);
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, params?: RequestOptions["params"], opts?: Pick<RequestOptions, "skipUnauthorizedHandler">) =>
    request<T>(path, { params, ...opts }),
  post: <T>(path: string, body?: unknown, opts?: Pick<RequestOptions, "skipUnauthorizedHandler">) =>
    request<T>(path, { method: "POST", body: body ?? {}, ...opts }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Field-level messages from a 400 `invalid` response, flattened for forms. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.details) return {};
  return Object.fromEntries(
    Object.entries(error.details).map(([field, messages]) => [field, Array.isArray(messages) ? messages.join(" ") : ""]),
  );
}
