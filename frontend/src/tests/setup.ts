import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { FakeWebSocket } from "./fakeWebSocket";

// Pages are code-split, so the first query of a test may wait for a chunk to load; under a busy CPU (parallel test files)
// that can exceed the 1 s default. Failing assertions still fail, they just no longer race the module loader.
configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.cookie = "sv_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});
