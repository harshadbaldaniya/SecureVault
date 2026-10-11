import { useCallback, useState } from "react";

import { api, ApiError } from "@/services/api";

import { copySecret } from "./clipboard";

type Kind = "credentials" | "notes";

/**
 * Reveal and copy, always triggered by a user click (never from an effect), so React StrictMode cannot fire
 * a second request (which would also burn a view-once share). Secrets stay in component state only, never in
 * the React Query cache or web storage. Every copy is a fresh server call so it is audited as COPY.
 */
export function useSecretActions(kind: Kind, field: "password" | "content") {
  const [revealed, setRevealed] = useState<{ title: string; value: string } | null>(null);
  const [clipboard, setClipboard] = useState<"copied" | "cleared" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchSecret = async (id: string, purpose: "view" | "copy") => {
    const result = await api.post<Record<string, string>>(`/vault/${kind}/${id}/reveal/`, { purpose });
    return result[field] ?? "";
  };

  const reveal = async (id: string, title: string) => {
    setError(null);
    setBusyId(id);
    try {
      setRevealed({ title, value: await fetchSecret(id, "view") });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reveal this secret.");
    } finally {
      setBusyId(null);
    }
  };

  const copy = async (id: string) => {
    setError(null);
    setBusyId(id);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard-unavailable");
      const value = await fetchSecret(id, "copy");
      await copySecret(value, () => setClipboard("cleared"));
      setClipboard("copied");
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
      else setError("Your browser blocked clipboard access. Use Reveal and copy the value manually.");
    } finally {
      setBusyId(null);
    }
  };

  const closeReveal = useCallback(() => setRevealed(null), []);
  const dismissClipboard = useCallback(() => setClipboard(null), []);

  return { revealed, closeReveal, reveal, copy, clipboard, dismissClipboard, busyId, error, clearError: () => setError(null) };
}
