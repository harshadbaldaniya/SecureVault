import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.cookie = "sv_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});
