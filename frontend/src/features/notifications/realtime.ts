import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/features/authentication/AuthContext";
import type { AppNotification } from "@/types/api";

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_LOCKDOWN = 4423;
const MAX_BACKOFF_MS = 30_000;

type Toast = Pick<AppNotification, "title" | "message" | "priority" | "link">;

/**
 * Real-time events over WebSocket. Notifications only: the server enforces every decision itself, so a
 * missed message never grants access. Reconnects with exponential backoff; stops for good when the server
 * says the session ended (4401) or a lockdown applies (4423).
 */
export function useRealtime(enabled: boolean) {
  const queryClient = useQueryClient();
  const { endSession, refresh } = useAuth();
  const [toast, setToast] = useState<Toast | null>(null);

  useEffect(() => {
    if (!enabled || typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const handle = (message: { type?: string; notification?: Toast }) => {
      switch (message.type) {
        case "notification":
          void queryClient.invalidateQueries({ queryKey: ["notifications"] });
          if (message.notification) setToast(message.notification);
          break;
        case "lockdown.activated":
        case "lockdown.active":
        case "lockdown.resolved":
          void refresh();
          void queryClient.invalidateQueries({ queryKey: ["lockdown"] });
          break;
        default:
          break;
      }
    };

    const connect = () => {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/ws/events/`);
      socket.onopen = () => {
        attempt = 0;
      };
      socket.onmessage = (event) => {
        try {
          handle(JSON.parse(String(event.data)));
        } catch {
          // ignore malformed frames
        }
      };
      socket.onclose = (event) => {
        if (stopped) return;
        if (event.code === CLOSE_UNAUTHENTICATED) return endSession("session_ended");
        if (event.code === CLOSE_LOCKDOWN) return endSession("lockdown");
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt) + Math.floor(Math.random() * 500);
        attempt += 1;
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [enabled, endSession, refresh, queryClient]);

  const dismissToast = useCallback(() => setToast(null), []);
  return { toast, dismissToast };
}
