/**
 * Copy a secret and try to clear the clipboard afterwards.
 *
 * Clearing is BEST-EFFORT. Browsers and operating systems may refuse clipboard access, clipboard managers
 * can keep history, and the user may copy something else in the meantime. The UI says so.
 */

export const CLEAR_AFTER_MS = 30_000;

export interface CopyHandle {
  /** Cancels the scheduled clear (used when the component unmounts early). */
  cancel: () => void;
}

export async function copySecret(text: string, onCleared: () => void, delayMs = CLEAR_AFTER_MS): Promise<CopyHandle> {
  await navigator.clipboard.writeText(text);

  const timer = setTimeout(async () => {
    try {
      // If we can read the clipboard and it no longer holds our secret, leave the user's newer copy alone.
      const current = await navigator.clipboard.readText().catch(() => null);
      if (current === null || current === text) await navigator.clipboard.writeText("");
    } catch {
      // Permission denied or document not focused: nothing more we can do.
    } finally {
      onCleared();
    }
  }, delayMs);

  return { cancel: () => clearTimeout(timer) };
}
