import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, fieldErrors, setUnauthorizedHandler } from "./api";

function respond(status: number, body?: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body ?? {}), { status, headers: { "Content-Type": "application/json" } });
}

describe("api client", () => {
  beforeEach(() => {
    document.cookie = "sv_csrftoken=token-123; path=/";
  });
  afterEach(() => setUnauthorizedHandler(null));

  it("sends the CSRF header on writes but not on reads", async () => {
    const fetchMock = vi.fn(async () => respond(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/departments/");
    await api.post("/departments/", { name: "Ops" });

    const [getCall, postCall] = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    expect((getCall![1].headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
    expect((postCall![1].headers as Record<string, string>)["X-CSRFToken"]).toBe("token-123");
    expect(postCall![1].credentials).toBe("same-origin");
  });

  it("fetches the CSRF cookie first when it is missing", async () => {
    document.cookie = "sv_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/csrf/")) {
        document.cookie = "sv_csrftoken=fresh-456; path=/";
        return respond(204);
      }
      return respond(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.post("/departments/", {});

    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0]![0]).toContain("/auth/csrf/");
    expect((calls[1]![1]!.headers as Record<string, string>)["X-CSRFToken"]).toBe("fresh-456");
  });

  it("turns the error envelope into an ApiError", async () => {
    vi.stubGlobal("fetch", async () => respond(400, { error: { code: "invalid", message: "Invalid input.", details: { code: ["Taken."] } } }));
    const error = await api.post("/departments/", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: "invalid", message: "Invalid input." });
    expect(fieldErrors(error)).toEqual({ code: "Taken." });
  });

  it("reports 401 to the unauthorized handler, unless skipped", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal("fetch", async () => respond(401, { error: { code: "not_authenticated", message: "Sign in." } }));

    await api.get("/auth/me/").catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);

    await api.post("/auth/login/", {}, { skipUnauthorizedHandler: true }).catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("maps network failures to a friendly error", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(api.get("/x/")).rejects.toMatchObject({ code: "network_error", status: 0 });
  });

  it("falls back to a generic message for non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>boom</html>", { status: 500 }));
    const error = (await api.get("/x/").catch((e: unknown) => e)) as ApiError;
    expect(error.message).not.toContain("boom");
    expect(error.status).toBe(500);
  });

  it("never touches web storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    vi.stubGlobal("fetch", async () => respond(200, { secret: "x" }));
    await api.get("/anything/");
    await api.post("/anything/", { a: 1 });
    expect(setItem).not.toHaveBeenCalled();
  });
});
