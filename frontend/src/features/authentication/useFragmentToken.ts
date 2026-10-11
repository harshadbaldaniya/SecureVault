import { useState } from "react";

/**
 * Reads `#token=...` once, keeps it in memory only, and removes it from the address bar
 * so it does not linger in browser history, screenshots or copied URLs.
 */
export function useFragmentToken(): string | null {
  const [token] = useState<string | null>(() => {
    const value = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
    if (value) window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return value;
  });
  return token;
}
