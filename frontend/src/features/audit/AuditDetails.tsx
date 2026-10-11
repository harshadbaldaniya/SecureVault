import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { CloseIcon } from "@/components/icons";
import { Badge } from "@/components/ui";
import type { AuditEntry } from "@/types/api";

const outcomeTone = { SUCCESS: "green", FAILURE: "red", DENIED: "amber" } as const;
const GAP = 8; // space between the button and the panel, and the minimum margin to the window edge
const WIDTH = 352; // 22rem
const NARROW = 640; // below this the panel becomes a compact sheet pinned to the bottom of the window

interface Position {
  top?: number;
  left?: number;
  bottom?: number;
  right?: number;
  maxHeight: number;
}

/** Puts the panel beside the button (right, else left), else under/over it, always inside the window. */
function place(anchor: DOMRect, panel: { width: number; height: number }, view: { width: number; height: number }): Position {
  if (view.width < NARROW) return { left: GAP, right: GAP, bottom: GAP, maxHeight: Math.round(view.height * 0.7) };
  const maxHeight = view.height - GAP * 2;
  const height = Math.min(panel.height, maxHeight);
  const clampTop = (top: number) => Math.max(GAP, Math.min(top, view.height - GAP - height));
  const clampLeft = (left: number) => Math.max(GAP, Math.min(left, view.width - GAP - panel.width));
  if (anchor.right + GAP + panel.width <= view.width - GAP) return { left: anchor.right + GAP, top: clampTop(anchor.top), maxHeight };
  if (anchor.left - GAP - panel.width >= GAP) return { left: anchor.left - GAP - panel.width, top: clampTop(anchor.top), maxHeight };
  // No room on either side: below the button if it fits, otherwise above it.
  const below = anchor.bottom + GAP;
  const top = below + height <= view.height - GAP ? below : Math.max(GAP, anchor.top - GAP - height);
  return { left: clampLeft(anchor.left), top, maxHeight };
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] gap-2 py-1.5">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-sm text-slate-800">{children}</dd>
    </div>
  );
}

/**
 * A non-modal floating panel with the details of one audit record. It sits above the page (portalled to <body>, so the
 * scrolling table cannot clip it) and leaves the table row untouched. It closes on Escape, on the close button and on a
 * click or tap outside it; the trigger button is excluded from "outside" so that its own click can toggle it.
 */
export function AuditDetails({ entry, anchor, onClose }: { entry: AuditEntry; anchor: HTMLElement; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const [position, setPosition] = useState<Position | null>(null);

  // Measure after render, and follow the button when the page or the window changes.
  useLayoutEffect(() => {
    const update = () => {
      if (!panel.current || !anchor.isConnected) return;
      const box = panel.current.getBoundingClientRect();
      setPosition(place(anchor.getBoundingClientRect(), { width: Math.min(WIDTH, window.innerWidth - GAP * 2), height: box.height }, { width: window.innerWidth, height: window.innerHeight }));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true); // capture: the page area and the table scroll on their own
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [anchor, entry.id]);

  // The record's row is gone (page changed, filters applied): nothing left to describe.
  useEffect(() => {
    if (!anchor.isConnected) onClose();
  });

  // Move focus into the panel once it is visible (a hidden element cannot take focus), so keyboard and screen-reader
  // users land on it straight away.
  const shown = position !== null;
  useEffect(() => {
    if (shown) closeButton.current?.focus({ preventScroll: true });
  }, [shown]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        anchor.focus({ preventScroll: true });
      }
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || anchor.contains(target)) return;
      onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [anchor, onClose]);

  const metadata = Object.keys(entry.metadata).length > 0;
  return createPortal(
    <div
      ref={panel}
      id={`audit-details-${entry.id}`}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      style={{ ...position, width: position?.right === undefined ? Math.min(WIDTH, window.innerWidth - GAP * 2) : undefined, visibility: position ? "visible" : "hidden" }}
      className="fixed z-50 flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl ring-1 ring-black/5"
    >
      <div className="flex items-start gap-2 border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Audit Record Details</p>
          <h2 id={titleId} className="mt-0.5 break-words text-base font-semibold text-slate-900">
            Record #{entry.sequence} — {entry.action}
          </h2>
        </div>
        <button
          ref={closeButton}
          type="button"
          aria-label="Close audit record details"
          onClick={() => {
            onClose();
            anchor.focus({ preventScroll: true });
          }}
          className="-mr-1 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-800"
        >
          <CloseIcon />
        </button>
      </div>
      <dl className="min-h-0 flex-1 divide-y divide-slate-100 overflow-y-auto px-4 py-2">
        <Row label="Record">#{entry.sequence}</Row>
        <Row label="Action">
          <span className="font-mono text-xs">{entry.action}</span>
        </Row>
        <Row label="Outcome">
          <Badge tone={outcomeTone[entry.outcome]}>{entry.outcome}</Badge>
        </Row>
        {entry.reason && <Row label="Reason">{entry.reason}</Row>}
        <Row label="Request ID">
          <span className="break-all font-mono text-xs">{entry.request_id}</span>
        </Row>
        {metadata && (
          <div className="py-2">
            <dt className="text-xs font-medium text-slate-500">Metadata</dt>
            <dd className="mt-1">
              <pre className="max-h-48 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-700">{JSON.stringify(entry.metadata, null, 2)}</pre>
            </dd>
          </div>
        )}
      </dl>
    </div>,
    document.body,
  );
}
