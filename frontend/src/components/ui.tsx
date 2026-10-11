import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

const cx = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(" ");

// --------------------------------------------------------------------------- Button

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/50",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export function Button({ variant = "primary", loading, disabled, className, children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed",
        variants[variant],
        className,
      )}
    >
      {loading && <Spinner small />}
      {children}
    </button>
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

export function Alert({ tone = "info", children, className }: { tone?: AlertTone; children: ReactNode; className?: string }) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("rounded-md border px-4 py-3 text-sm", tones[tone], className)}>
      {children}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center">
      <p className="font-medium text-slate-700">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
    </div>
  );
}

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

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} {...rest} className={cx(controlClass, className)}>
      {children}
    </select>
  );
});

export function Checkbox({ label, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <input id={id} type="checkbox" {...rest} className="size-4 rounded border-slate-300 text-brand-600" />
      <label htmlFor={id} className="text-sm text-slate-700">
        {label}
      </label>
    </div>
  );
}

// --------------------------------------------------------------------------- Dialogs

interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

/** Native <dialog>: focus trap, Escape to close and inert background come from the browser. */
export function Dialog({ open, title, onClose, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.() ?? dialog.setAttribute("open", "");
    if (!open && dialog.open) dialog.close?.() ?? dialog.removeAttribute("open");
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={onClose}
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-lg p-0 shadow-xl backdrop:bg-slate-900/50"
    >
      {open && (
        <div className="p-6">
          <h2 id={titleId} className="mb-4 text-lg font-semibold">
            {title}
          </h2>
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
    <Dialog open={open} title={title} onClose={onCancel}>
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
      <div className="flex gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </nav>
  );
}

export function Table({ caption, headers, children }: { caption: string; headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
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
