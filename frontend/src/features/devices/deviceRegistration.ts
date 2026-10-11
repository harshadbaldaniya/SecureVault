import { useQuery } from "@tanstack/react-query";

import { api } from "@/services/api";
import type { Device } from "@/types/api";

/**
 * A SHA-256 over stable browser signals. It is only a RISK SIGNAL for the server: these values can be spoofed
 * or change (updates, monitors). The device's identity is the HttpOnly cookie the server issues, which this
 * code never sees.
 */
export async function deviceFingerprint(): Promise<string> {
  try {
    const signals = [
      navigator.userAgent,
      navigator.language,
      String(navigator.hardwareConcurrency ?? ""),
      `${window.screen?.width ?? 0}x${window.screen?.height ?? 0}x${window.screen?.colorDepth ?? 0}`,
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    ].join("|");
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(signals));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return ""; // no WebCrypto (very old browser or insecure context): the server still identifies the device
  }
}

/** Identify this browser's device once per app session (React Query de-duplicates concurrent calls). */
export function useDeviceRegistration(enabled: boolean) {
  return useQuery({
    queryKey: ["device", "current"],
    queryFn: async () => api.post<Device>("/devices/register/", { fingerprint: await deviceFingerprint() }),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}
