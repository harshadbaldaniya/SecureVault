import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp, unauthenticated } from "@/tests/utils";

const logos = () => screen.getAllByRole("link", { name: "SecureVault home" });

describe("SecureVault branding", () => {
  it("is the same mark on the landing, get-started and sign-in pages", async () => {
    for (const path of ["/", "/get-started", "/login", "/forgot-password"]) {
      mockFetch({ "GET /auth/me/": unauthenticated });
      const { unmount } = renderApp(path);
      await screen.findByRole("heading", { level: 1 });
      const [logo] = logos();
      expect(logo, path).toHaveAttribute("href", "/");
      expect(logo!.textContent, path).toBe("SecureVault");
      expect(logo!.querySelector("svg"), path).not.toBeNull(); // the shield mark, not just text
      unmount();
    }
  });

  it("appears once per shared layout region on every signed-in page, never inside the page content", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE") },
      "GET /notifications/": { body: { count: 0, next: null, previous: null, results: [] } },
    });
    for (const path of ["/", "/notifications", "/no-such-page"]) {
      const { unmount } = renderApp(path);
      await screen.findByRole("navigation", { name: "Main" });
      const found = logos();
      // One in the mobile header and one in the desktop sidebar (CSS shows one at a time); none in <main>.
      expect(found, path).toHaveLength(2);
      const aside = document.querySelector("aside#sidebar")!;
      const header = document.querySelector("header")!;
      expect(found.filter((l) => aside.contains(l)), path).toHaveLength(1);
      expect(found.filter((l) => header.contains(l)), path).toHaveLength(1);
      expect(within(screen.getByRole("main")).queryByRole("link", { name: "SecureVault home" }), path).not.toBeInTheDocument();
      unmount();
    }
  });

  it("is also shown on the lockdown notice that replaces the app for a locked-out employee", async () => {
    mockFetch({
      "GET /auth/me/": { body: makeMe("EMPLOYEE", { lockdown: { id: "l1", scope: "GLOBAL", target_user_id: null, triggered_at: "2026-10-11T10:00:00Z", is_active: true } }) },
    });
    renderApp("/vault");
    await screen.findByRole("heading", { name: "Emergency lockdown in effect" });
    expect(logos()).toHaveLength(1);
  });
});
