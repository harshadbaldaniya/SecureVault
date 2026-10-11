import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/features/authentication/AuthContext";
import type { AppNotification } from "@/types/api";

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_LOCKDOWN = 4423;
const MAX_BACKOFF_MS = 30_000;

export type Toast = Pick<AppNotification, "title" | "message" | "priority" | "link"> & { id?: string };
/** A toast as shown: the stored notification plus a key that is unique even if the server sent no id. */
export type ToastItem = Toast & { key: string };

const MAX_KEPT = 8; // toasts held in memory; what is *shown* is decided by arrangeToasts
const REMEMBERED_IDS = 200;

/**
 * Real-time events over WebSocket. Notifications only: the server enforces every decision itself, so a
 * missed message never grants access. Reconnects with exponential backoff; stops for good when the server
 * says the session ended (4401) or a lockdown applies (4423).
 */
export function useRealtime(enabled: boolean) {
  const queryClient = useQueryClient();
  const { endSession, refresh } = useAuth();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Notification ids already shown. A toast the user dismissed must not come back if the server delivers the same
  // notification again (reconnect, duplicate delivery); the stored notification itself is untouched either way.
  const shown = useRef<Set<string>>(new Set());
  const sequence = useRef(0);

  useEffect(() => {
    if (!enabled || typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const show = (notification: Toast) => {
      if (notification.id) {
        if (shown.current.has(notification.id)) return;
        shown.current.add(notification.id);
        if (shown.current.size > REMEMBERED_IDS) shown.current.delete(shown.current.values().next().value as string);
      }
      sequence.current += 1;
      const item: ToastItem = { ...notification, key: notification.id ?? `local-${sequence.current}` };
      setToasts((current) => {
        const next = [...current, item];
        // Over the limit, forget the oldest ordinary toast first; a HIGH or CRITICAL warning is dropped only as a last resort.
        while (next.length > MAX_KEPT) {
          const victim = next.findIndex((t) => t.priority !== "HIGH" && t.priority !== "CRITICAL");
          next.splice(victim === -1 ? 0 : victim, 1);
        }
        return next;
      });
    };

    const handle = (message: { type?: string; notification?: Toast }) => {
      switch (message.type) {
        case "notification":
          void queryClient.invalidateQueries({ queryKey: ["notifications"] });
          if (message.notification) show(message.notification);
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

  /** Removes the toast from view only; the notification stays stored, and read or unread, exactly as it was. */
  const dismissToast = useCallback((key: string) => setToasts((current) => current.filter((t) => t.key !== key)), []);
  return { toasts, dismissToast };
}
