import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScrollManager } from "./ScrollManager";

function Harness() {
  const navigate = useNavigate();
  return (
    <>
      <ScrollManager />
      <button onClick={() => navigate("/get-started")}>push</button>
      <button onClick={() => navigate("/#security")}>push section</button>
      <button onClick={() => navigate("/login", { replace: true })}>replace</button>
      <button onClick={() => navigate(-1)}>back</button>
      <button onClick={() => navigate(1)}>forward</button>
      <Routes>
        <Route path="*" element={<p>page</p>} />
      </Routes>
    </>
  );
}

const scrollTo = vi.fn();
const scrollAt = (y: number) => {
  Object.defineProperty(window, "scrollY", { value: y, configurable: true });
  window.dispatchEvent(new Event("scroll"));
};
const lastTop = () => (scrollTo.mock.calls.at(-1)![0] as ScrollToOptions).top;

describe("scroll restoration for page-to-page navigation", () => {
  beforeEach(() => {
    scrollTo.mockClear();
    vi.stubGlobal("scrollTo", scrollTo);
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
    scrollAt(0);
  });

  it("opens a newly navigated page at the top, even when the previous page was scrolled", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Harness />
      </MemoryRouter>,
    );
    scrollAt(2400); // bottom of the landing page
    await user.click(screen.getByText("push"));
    expect(lastTop()).toBe(0);
    expect((scrollTo.mock.calls.at(-1)![0] as ScrollToOptions).behavior).toBe("instant"); // not animated by smooth scrolling
  });

  it("also starts at the top for a replace navigation such as an authentication redirect", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/vault"]}>
        <Harness />
      </MemoryRouter>,
    );
    scrollAt(900);
    await user.click(screen.getByText("replace"));
    expect(lastTop()).toBe(0);
  });

  it("restores where you were on Back and Forward", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Harness />
      </MemoryRouter>,
    );
    scrollAt(2400);
    await user.click(screen.getByText("push")); // -> /get-started, reset to the top
    scrollAt(0);
    scrollAt(350); // scrolled a little down the get-started page
    await user.click(screen.getByText("back")); // -> landing at 2400 again
    expect(lastTop()).toBe(2400);
    await user.click(screen.getByText("forward"));
    expect(lastTop()).toBe(350);
  });

  it("leaves navigation that targets a section alone, so anchors keep working", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/get-started"]}>
        <Harness />
      </MemoryRouter>,
    );
    scrollTo.mockClear();
    await act(async () => {});
    await user.click(screen.getByText("push section"));
    expect(scrollTo).not.toHaveBeenCalled();
  });
});
