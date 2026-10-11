import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

/**
 * Scroll behaviour for page-to-page navigation. A single-page app does not reload, so the window keeps whatever scroll
 * position the previous page had: a link clicked at the bottom of the landing page would open the next page near its
 * bottom. This resets to the top for every new navigation, and restores the remembered position on Back/Forward.
 *
 * Links that carry a #fragment are left alone: the page that owns the section scrolls to it itself (and the browser does
 * for same-page anchors). Only the window is managed; the signed-in app scrolls inside its own <main>, which AppLayout
 * resets separately.
 */
export function ScrollManager() {
  const { key, hash } = useLocation();
  const type = useNavigationType();
  const positions = useRef(new Map<string, number>());
  const current = useRef(key);

  // The browser's own restoration runs before this app has rendered the destination, so it would restore onto the wrong page.
  useLayoutEffect(() => {
    if (!("scrollRestoration" in window.history)) return;
    const before = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    return () => {
      window.history.scrollRestoration = before;
    };
  }, []);

  useEffect(() => {
    const remember = () => positions.current.set(current.current, window.scrollY);
    window.addEventListener("scroll", remember, { passive: true });
    return () => window.removeEventListener("scroll", remember);
  }, []);

  useLayoutEffect(() => {
    current.current = key;
    if (hash) return;
    const top = type === "POP" ? (positions.current.get(key) ?? 0) : 0;
    // "instant": the page uses smooth scrolling for anchors, and a route change should not animate.
    window.scrollTo({ top, left: 0, behavior: "instant" as ScrollBehavior });
  }, [key, hash, type]);

  return null;
}
