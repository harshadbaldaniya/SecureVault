import { forwardRef, useEffect, useId, useRef, useState, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ComponentProps, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Link } from "react-router-dom";

import { CloseIcon, UploadIcon } from "./icons";

const cx = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(" ");

// --------------------------------------------------------------------------- Button

/*
 * Action hierarchy
 *   primary       the main action of a page or form (one per section)
 *   secondary     useful supporting actions that should stay visible: back, download, open another page
 *   ghost         low-emphasis actions inside rows and toolbars
 *   danger        a confirmed destructive action (the confirmation button of a dialog)
 *   danger-ghost  a destructive action offered in a row (always followed by a confirmation dialog)
 * Genuine inline references use TextLink; switching between two views of the same data uses Segmented.
 */
export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "danger-ghost";
export type ButtonSize = "md" | "sm";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400 aria-pressed:bg-brand-50 aria-pressed:text-brand-700 aria-pressed:ring-brand-600",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/50",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  "danger-ghost": "text-red-700 hover:bg-red-50 disabled:text-slate-400",
};
const sizes: Record<ButtonSize, string> = { md: "min-h-10 px-4", sm: "min-h-8 px-2.5" };

/** The one place button styling lives; Button and LinkButton both use it. */
export function buttonClasses({ variant = "primary", size = "md", className }: { variant?: ButtonVariant; size?: ButtonSize; className?: string | undefined }) {
  return cx("inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:cursor-not-allowed", sizes[size], variants[variant], className);
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export function Button({ variant = "primary", size = "md", loading, disabled, className, children, ...rest }: ButtonProps) {
  return (
    <button type="button" {...rest} disabled={disabled || loading} aria-busy={loading || undefined} className={buttonClasses({ variant, size, className })}>
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

type RouterTarget = { to: string } & Omit<ComponentProps<typeof Link>, "to" | "className">;
type AnchorTarget = { to?: undefined; href: string } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className">;

function Anchor({ className, children, ...target }: { className: string; children: ReactNode } & (RouterTarget | AnchorTarget)) {
  if (target.to !== undefined) {
    const { to, ...rest } = target as RouterTarget;
    return (
      <Link to={to} className={className} {...rest}>
        {children}
      </Link>
    );
  }
  const { href, ...rest } = target as AnchorTarget;
  return (
    <a href={href} className={className} {...rest}>
      {children}
    </a>
  );
}

/** A link that looks like a button: `to` for navigation inside the app, `href` for downloads and external addresses. */
export function LinkButton({ variant = "secondary", size = "md", className, children, ...target }: { variant?: ButtonVariant; size?: ButtonSize; className?: string; children: ReactNode } & (RouterTarget | AnchorTarget)) {
  return (
    <Anchor className={buttonClasses({ variant, size, className })} {...target}>
      {children}
    </Anchor>
  );
}

/** A lightweight inline reference (low-priority navigation inside text or beside a field). */
export function TextLink({ className, children, ...target }: { className?: string; children: ReactNode } & (RouterTarget | AnchorTarget)) {
  return (
    <Anchor className={cx("rounded-sm py-1.5 font-medium text-brand-700 underline-offset-2 hover:underline", className)} {...target}>
      {children}
    </Anchor>
  );
}

/** Two or more views of the same data (for example chart / table). The selected one is marked, not just coloured. */
export function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: Array<{ value: T; label: string }>; onChange: (value: T) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex shrink-0 rounded-md bg-slate-100 p-0.5">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={cx(
              "min-h-8 rounded px-3 text-xs font-medium transition-colors",
              selected ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:text-slate-900",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------- Feedback

export function Spinner({ small }: { small?: boolean }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cx(
        "inline-block animate-spin rounded-full border-2 border-current border-t-transparent",
        small ? "size-4" : "size-6",
      )}
    />
  );
}

export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 p-12 text-slate-500" aria-live="polite">
      <Spinner /> <span>{label}</span>
    </div>
  );
}

type AlertTone = "error" | "success" | "warning" | "info";
const tones: Record<AlertTone, string> = {
  error: "border-red-200 bg-red-50 text-red-800",
  success: "border-green-200 bg-green-50 text-green-800",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-blue-200 bg-blue-50 text-blue-900",
};

export function Alert({ tone = "info", children, className, action }: { tone?: AlertTone; children: ReactNode; className?: string; action?: ReactNode }) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("rounded-md border px-4 py-3 text-sm", tones[tone], className)}>
      {action ? (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">{children}</div>
          <div className="shrink-0">{action}</div>
        </div>
      ) : (
        children
      )}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center">
      <p className="font-medium text-slate-700">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

// Colour convention used across the app: green = healthy/done, amber = needs attention or pending, red = severe, failed or
// blocked, blue = informational or in progress, slate = neutral or inactive. The text always carries the meaning too.
const badgeTones: Record<string, string> = {
  green: "bg-green-100 text-green-800",
  red: "bg-red-100 text-red-800",
  amber: "bg-amber-100 text-amber-900",
  slate: "bg-slate-100 text-slate-700",
  blue: "bg-blue-100 text-blue-800",
};

export function Badge({ tone = "slate", children }: { tone?: keyof typeof badgeTones; children: ReactNode }) {
  return <span className={cx("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", badgeTones[tone])}>{children}</span>;
}

// --------------------------------------------------------------------------- Tabs

/** Shared look for every tab strip so the pages stay identical: one row, underline for the selected tab. */
export const tabListClass = "mb-4 flex flex-wrap gap-x-1 border-b border-slate-200";
export const tabClass = (selected: boolean) =>
  `-mb-px border-b-2 px-4 py-2 text-sm font-medium ${selected ? "border-brand-600 text-brand-700" : "border-transparent text-slate-600 hover:text-slate-900"}`;

// --------------------------------------------------------------------------- Layout

export function Card({ title, description, actions, children }: { title?: string; description?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200">
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-base font-semibold">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

// --------------------------------------------------------------------------- Form fields

interface FieldProps {
  label: string;
  error?: string | undefined;
  hint?: string;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby": string | undefined }) => ReactNode;
}

/** Associates label, hint and error text with the control for screen readers. */
export function Field({ label, error, hint, children }: FieldProps) {
  const id = useId();
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

const controlClass =
  "block min-h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm shadow-sm placeholder:text-slate-400 aria-[invalid=true]:border-red-500 disabled:bg-slate-100";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} {...rest} className={cx(controlClass, className)} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} {...rest} className={cx(controlClass, "min-h-32 py-2 font-mono", className)} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} {...rest} className={cx(controlClass, className)}>
      {children}
    </select>
  );
});

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: string }>(function Checkbox({ label, ...rest }, ref) {
  const id = useId();
  return (
    <div className="flex min-h-8 items-center gap-2">
      <input ref={ref} id={id} type="checkbox" {...rest} className="size-4 rounded border-slate-300 text-brand-600" />
      <label htmlFor={id} className="cursor-pointer py-1 text-sm text-slate-700">
        {label}
      </label>
    </div>
  );
});

/**
 * File picker with a real button and a readable file name instead of the browser's native "Choose File / No file chosen".
 * The native input stays in the DOM (visually hidden but focusable) so keyboard use, screen readers and `accept`
 * validation work as before; the visible button is its label.
 */
export const FileInput = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange" | "children"> & { label?: string; fileName: string | null; onFile: (file: File | null) => void }>(function FileInput(
  { label = "Choose file", fileName, onFile, className, id, ...rest },
  ref,
) {
  const generated = useId();
  const inputId = id ?? generated;
  const statusId = `${inputId}-status`;
  return (
    <div className={cx("flex flex-wrap items-center gap-3", className)}>
      <input ref={ref} id={inputId} type="file" className="peer sr-only" aria-describedby={statusId} onChange={(event) => onFile(event.target.files?.[0] ?? null)} {...rest} />
      <label
        htmlFor={inputId}
        className={cx(
          buttonClasses({ variant: "secondary" }),
          "cursor-pointer peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand-600 peer-disabled:cursor-not-allowed peer-disabled:text-slate-400",
        )}
      >
        <UploadIcon />
        {label}
      </label>
      <span id={statusId} aria-live="polite" className={cx("min-w-0 max-w-full truncate text-sm", fileName ? "font-medium text-slate-800" : "text-slate-500")}>
        {fileName ?? "No file selected"}
      </span>
    </div>
  );
});

// --------------------------------------------------------------------------- Dialogs

interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Header "×" button. On by default; confirmation questions already have an explicit Cancel and turn it off. */
  closeButton?: boolean;
}

/** A short fingerprint of everything typed into the forms inside `root` (hashed, so no second copy of a secret is kept). */
function formFingerprint(root: HTMLElement): string {
  let hash = 5381;
  const feed = (text: string) => {
    for (let i = 0; i < text.length; i += 1) hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  };
  // Every field, named or not: a controlled input without a `name` would be invisible to FormData.
  root.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("form input, form select, form textarea").forEach((field, index) => {
    if (field instanceof HTMLInputElement && (field.type === "checkbox" || field.type === "radio")) feed(`${index}:${field.checked}\u0000`);
    else if (field instanceof HTMLInputElement && field.type === "file") feed(`${index}:${Array.from(field.files ?? [], (f) => f.name).join(",")}\u0000`);
    else feed(`${index}:${field.value}\u0000`);
  });
  return String(hash);
}

/**
 * Native <dialog>: focus trap, Escape to close, inert background and focus return to the opener come from the browser.
 * Escape and the × button never lose typed form input silently: once something inside a form was edited they ask first.
 * (A form's own Cancel button is an explicit choice and closes immediately.)
 */
export function Dialog({ open, title, onClose, children, closeButton = true }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const touched = useRef(false);
  const baseline = useRef<string | null>(null);
  const [discarding, setDiscarding] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // Fallbacks cover environments without the <dialog> API (older browsers, jsdom).
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
    touched.current = false;
    baseline.current = null;
    setDiscarding(false);
    // What the form looked like when it opened. It is refreshed on every focus until the first edit (below), so values
    // that arrive a moment after opening, or an edit made before this ran, can never be mistaken for the starting point.
    if (open && ref.current) baseline.current = formFingerprint(ref.current);
  }, [open]);

  /** Unsaved = the user touched a form AND its content now differs from how it opened, so typing and reverting is clean. */
  const isDirty = () => touched.current && baseline.current !== null && ref.current !== null && formFingerprint(ref.current) !== baseline.current;

  /** The × button: close at once, or ask first when a form inside was edited. */
  const requestClose = () => {
    if (isDirty()) {
      setDiscarding(true);
      return;
    }
    onClose();
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(event) => {
        // Escape: keep the dialog open while we ask about unsaved edits.
        if (isDirty()) {
          event.preventDefault();
          setDiscarding(true);
        } else onClose();
      }}
      onFocus={() => {
        if (!touched.current && ref.current) baseline.current = formFingerprint(ref.current);
      }}
      onInput={(event) => {
        if ((event.target as HTMLElement).closest("form")) touched.current = true;
      }}
      onClick={(event) => {
        // Buttons such as "Generate" change a field without an input event.
        if ((event.target as HTMLElement).closest("form button")) touched.current = true;
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-lg p-0 shadow-xl backdrop:bg-slate-900/50"
    >
      {open && (
        <div className="relative p-6">
          {closeButton && (
            <button
              type="button"
              aria-label="Close dialog"
              onClick={requestClose}
              className="absolute right-3 top-3 inline-flex size-9 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <CloseIcon />
            </button>
          )}
          <h2 id={titleId} className={cx("mb-4 text-lg font-semibold", closeButton && "pr-10")}>
            {title}
          </h2>
          {discarding && (
            <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <span>Discard your unsaved changes?</span>
              <span className="flex gap-2">
                <Button size="sm" variant="secondary" autoFocus onClick={() => setDiscarding(false)}>
                  Keep editing
                </Button>
                <Button size="sm" variant="danger" onClick={onClose}>
                  Discard
                </Button>
              </span>
            </div>
          )}
          {children}
        </div>
      )}
    </dialog>
  );
}

interface ConfirmProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Confirmation step for sensitive or destructive actions. */
export function ConfirmDialog({ open, title, message, confirmLabel, danger, busy, error, onConfirm, onCancel }: ConfirmProps) {
  return (
    <Dialog open={open} title={title} onClose={onCancel} closeButton={false}>
      <div className="space-y-4">
        <div className="text-sm text-slate-600">{message}</div>
        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

// --------------------------------------------------------------------------- Pagination

export function Pagination({ page, pageSize, count, onPage }: { page: number; pageSize: number; count: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  return (
    <nav aria-label="Pagination" className="mt-4 flex items-center justify-between text-sm text-slate-600">
      <span>
        Page {page} of {pages} · {count} total
      </span>
      {pages > 1 && (
        <div className="flex gap-2">
          <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            Previous
          </Button>
          <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
            Next
          </Button>
        </div>
      )}
    </nav>
  );
}

// A scrollable table can be much taller than the window, so an outline around the whole box would be huge. Focus is shown on
// the header row instead (tinted, with a thick underline), which always sits at the top of the region.
const TABLE_FOCUS =
  "focus-visible:outline-none [&:focus-visible_thead]:bg-brand-50 [&:focus-visible_thead_th]:text-brand-700 [&:focus-visible_thead_th]:shadow-[inset_0_-3px_0_0_var(--color-brand-600)]";

export function Table({ caption, headers, children }: { caption: string; headers: string[]; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrolls, setScrolls] = useState(false);

  // A horizontally scrolling region must be reachable by keyboard (WCAG 2.1.1), but only when it actually overflows,
  // so short tables do not add a pointless tab stop.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setScrolls(el.scrollWidth > el.clientWidth + 1);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  });

  return (
    <div ref={ref} className={cx("overflow-x-auto rounded-lg ring-1 ring-slate-200", scrolls && TABLE_FOCUS)} {...(scrolls ? { role: "region", tabIndex: 0, "aria-label": `${caption} (scrollable)` } : {})}>
      <table className="min-w-full divide-y divide-slate-200 bg-white text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {headers.map((header) => (
              <th key={header} scope="col" className="px-4 py-3 font-medium">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}
