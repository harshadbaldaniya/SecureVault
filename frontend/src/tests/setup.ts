import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { FakeWebSocket } from "./fakeWebSocket";

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.cookie = "sv_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});
