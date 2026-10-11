import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { CloseIcon } from "@/components/icons";
import { api } from "@/services/api";
import type { AppNotification } from "@/types/api";

import type { ToastItem } from "./realtime";

/** Ordinary notices go away on their own; HIGH and CRITICAL are security warnings and stay until the user dismisses them. */
export const TOAST_SECONDS = 5;
const STICKY: ReadonlyArray<AppNotification["priority"]> = ["HIGH", "CRITICAL"];

// Same scale as alert severity and the Notifications page.
const ACCENT = {
  LOW: "border-l-slate-400",
  NORMAL: "border-l-blue-500",
  HIGH: "border-l-red-600",
  CRITICAL: "border-l-red-600",
} as const;
const SEVERITY_TEXT = { LOW: "Low priority", NORMAL: "", HIGH: "High priority", CRITICAL: "Critical" } as const;

const RANK = { LOW: 0, NORMAL: 1, HIGH: 2, CRITICAL: 3 } as const;
const BASE_SLOTS = 2;

/**
 * Decides which toasts get a card. Two slots normally; every CRITICAL warning always gets one (so never hidden), and
 * the rest go to the highest priority, newest first. Whatever does not fit is summarised, not silently dropped.
 */
export function arrangeToasts(toasts: ToastItem[]): { shown: ToastItem[]; hidden: ToastItem[] } {
  const slots = Math.max(BASE_SLOTS, toasts.filter((t) => t.priority === "CRITICAL").length);
  const ranked = toasts.map((toast, index) => ({ toast, index })).sort((a, b) => RANK[b.toast.priority] - RANK[a.toast.priority] || b.index - a.index);
  const keep = new Set(ranked.slice(0, slots).map((r) => r.toast.key));
  return { shown: toasts.filter((t) => keep.has(t.key)), hidden: toasts.filter((t) => !keep.has(t.key)) };
}

function MoreToasts({ hidden, onClear }: { hidden: ToastItem[]; onClear: () => void }) {
  const urgent = hidden.filter((t) => STICKY.includes(t.priority)).length;
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
      <span className="text-slate-700">
        +{hidden.length} more {hidden.length === 1 ? "notification" : "notifications"}
        {urgent > 0 && <span className="font-medium text-red-700"> ({urgent} high priority)</span>}
      </span>
      <Link to="/notifications" onClick={onClear} className="rounded-sm py-1 font-medium text-brand-700 underline-offset-2 hover:underline">
        View all
      </Link>
    </div>
  );
}

function ToastCard({ toast, onDismiss, onOpen }: { toast: ToastItem; onDismiss: () => void; onOpen: () => void }) {
  const sticky = STICKY.includes(toast.priority);
  const [paused, setPaused] = useState(false);
  const remaining = useRef(TOAST_SECONDS * 1000);
  const dismiss = useRef(onDismiss);
  dismiss.current = onDismiss;

  // Counts down only while the pointer is away and focus is outside; the time already used is kept across pauses.
  useEffect(() => {
    if (sticky || paused) return;
    const started = Date.now();
    const timer = setTimeout(() => dismiss.current(), remaining.current);
    return () => {
      clearTimeout(timer);
      remaining.current = Math.max(0, remaining.current - (Date.now() - started));
    };
  }, [sticky, paused]);

  const severity = SEVERITY_TEXT[toast.priority];
  return (
    <div
      className={`rounded-md border border-l-4 border-slate-200 bg-white p-3 text-sm shadow-lg ${ACCENT[toast.priority]}`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPaused(false);
      }}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-slate-900">
            {severity && <span className="sr-only">{severity}: </span>}
            {toast.title}
          </p>
          {toast.message && <p className="mt-0.5 line-clamp-2 hidden text-xs text-slate-600 sm:block">{toast.message}</p>}
          {toast.link && (
            <Link to={toast.link} onClick={onOpen} className="mt-1.5 inline-block rounded-sm py-1 text-xs font-medium text-brand-700 underline-offset-2 hover:underline">
              Open
            </Link>
          )}
        </div>
        <button
          type="button"
          aria-label={`Dismiss: ${toast.title}`}
          onClick={onDismiss}
          className="-mr-1 -mt-1 inline-flex size-7 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          <CloseIcon />
        </button>
      </div>
    </div>
  );
}

/**
 * Live notifications. Dismissing only hides the toast. Opening one follows its link, hides it and marks the stored
 * notification read (the same thing the Notifications page does for its Open link).
 */
export function ToastStack({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (key: string) => void }) {
  const queryClient = useQueryClient();
  const markRead = useMutation({
    mutationFn: (id: string) => api.post(`/notifications/${id}/read/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const { shown, hidden } = arrangeToasts(toasts);

  // On a phone the stack spans the bottom of the screen. Tell the page how tall it is (--toast-space, used as bottom
  // padding of <main> below the sm breakpoint) so everything can still be scrolled up above the toasts and tapped.
  const stack = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--toast-space", `${stack.current ? stack.current.offsetHeight : 0}px`);
    return () => {
      root.style.removeProperty("--toast-space");
    };
  });

  // An ordinary notice that never got a card is only counted in the summary for a few seconds, like a card would be.
  const stale = hidden.filter((t) => !STICKY.includes(t.priority)).map((t) => t.key).join("|");
  useEffect(() => {
    if (!stale) return;
    const timer = setTimeout(() => stale.split("|").forEach(onDismiss), TOAST_SECONDS * 1000);
    return () => clearTimeout(timer);
  }, [stale, onDismiss]);

  if (toasts.length === 0) return null;
  return (
    <div ref={stack} className="pointer-events-none fixed inset-x-4 bottom-4 z-40 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-4 sm:w-80" role="region" aria-label="New notifications" aria-live="polite">
      {shown.map((toast) => (
        <div key={toast.key} className="pointer-events-auto w-full">
          <ToastCard
            toast={toast}
            onDismiss={() => onDismiss(toast.key)}
            onOpen={() => {
              if (toast.id) markRead.mutate(toast.id);
              onDismiss(toast.key);
            }}
          />
        </div>
      ))}
      {hidden.length > 0 && (
        <div className="pointer-events-auto w-full">
          <MoreToasts hidden={hidden} onClear={() => hidden.forEach((t) => onDismiss(t.key))} />
        </div>
      )}
    </div>
  );
}
