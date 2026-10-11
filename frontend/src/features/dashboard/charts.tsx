import { useId, useState, type ReactNode } from "react";

/*
 * Small, dependency-free chart pieces following the dataviz method:
 * one series = one color (series slot 1), thin marks (<= 24px) with a 4px rounded data end and a square
 * baseline, hairline axes, selective labels, a hover/focus tooltip on every mark, and a table view twin.
 * Text always uses text colors; only marks carry the series color.
 */

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

export function StatTile({ label, value, hint, children }: { label: string; value: number | string; hint?: ReactNode; children?: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <p className="text-sm text-slate-600">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{typeof value === "number" ? compact.format(value) : value}</p>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
      {children}
    </div>
  );
}

export type StatusLevel = "good" | "warning" | "serious" | "critical";
const STATUS_ICON: Record<StatusLevel, string> = { good: "✓", warning: "!", serious: "▲", critical: "⛔" };

/** Status = color + icon + label, never color alone. */
export function StatusMark({ level, label }: { level: StatusLevel; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-slate-800">
      <span aria-hidden="true" className="inline-flex size-5 items-center justify-center rounded-full text-xs font-bold text-white" style={{ backgroundColor: `var(--viz-status-${level})` }}>
        {STATUS_ICON[level]}
      </span>
      {label}
    </span>
  );
}

/** A single ratio against its total. Track is a lighter step of the same ramp. */
export function Meter({ label, value, total, unit }: { label: string; value: number; total: number; unit: string }) {
  const share = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-semibold text-slate-900">
          {value} of {total} {unit} ({share}%)
        </span>
      </div>
      <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={total} aria-valuenow={value} className="mt-2 h-2 overflow-hidden rounded-full" style={{ backgroundColor: "var(--viz-track)" }}>
        <div className="h-full rounded-full" style={{ width: `${share}%`, backgroundColor: "var(--viz-series-1)" }} />
      </div>
    </div>
  );
}

export interface Datum {
  label: string;
  value: number;
}

function ChartFrame({ title, caption, data, valueLabel, children }: { title: string; caption?: string; data: Datum[]; valueLabel: string; children: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  const headingId = useId();
  return (
    <figure aria-labelledby={headingId} className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 id={headingId} className="text-sm font-semibold text-slate-900">
            {title}
          </h3>
          {caption && <p className="text-xs text-slate-500">{caption}</p>}
        </div>
        <button type="button" className="text-xs text-brand-700 underline" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>
      {asTable ? (
        <table className="w-full text-sm">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th scope="col" className="py-1 font-medium">
                Category
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                {valueLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.label} className="border-t border-slate-100">
                <td className="py-1">{d.label}</td>
                <td className="py-1 text-right tabular-nums">{d.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        children
      )}
    </figure>
  );
}

/** Vertical columns along a time axis. Labels: only the latest and the peak; everything else is in the tooltip. */
export function ColumnChart({ title, caption, data, valueLabel }: { title: string; caption?: string; data: Datum[]; valueLabel: string }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  const peak = data.reduce((best, d, i) => (d.value > (data[best]?.value ?? -1) ? i : best), 0);
  const labelled = new Set([data.length - 1, peak]);
  return (
    <ChartFrame title={title} caption={caption} data={data} valueLabel={valueLabel}>
      <div className="relative">
        <div className="flex h-40 items-end justify-around border-b" style={{ borderColor: "var(--viz-baseline)" }}>
          {data.map((d, i) => (
            <div key={d.label} className="relative flex h-full flex-1 items-end justify-center">
              {labelled.has(i) && d.value > 0 && (
                <span className="absolute text-xs text-slate-600" style={{ bottom: `calc(${(d.value / max) * 100}% + 4px)` }}>
                  {d.value}
                </span>
              )}
              <button
                type="button"
                aria-label={`${d.label}: ${d.value} ${valueLabel.toLowerCase()}`}
                onPointerEnter={() => setActive(i)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
                className="flex h-full w-full items-end justify-center"
              >
                <span
                  className="block w-full max-w-6 rounded-t transition-opacity"
                  style={{ height: `${Math.max((d.value / max) * 100, d.value > 0 ? 2 : 0)}%`, backgroundColor: "var(--viz-series-1)", opacity: active === null || active === i ? 1 : 0.55 }}
                />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-1 flex justify-around text-xs text-slate-500">
          {data.map((d) => (
            <span key={d.label} className="flex-1 text-center">
              {d.label}
            </span>
          ))}
        </div>
        {active !== null && data[active] && (
          <div role="tooltip" className="pointer-events-none absolute top-0 rounded-md bg-slate-900 px-2 py-1 text-xs text-white shadow" style={{ left: `${((active + 0.5) / data.length) * 100}%`, transform: "translateX(-50%)" }}>
            <strong className="block text-sm">{data[active].value}</strong>
            {data[active].label}
          </div>
        )}
      </div>
    </ChartFrame>
  );
}

/** Horizontal bars for ordered categories; with no value axis, each bar carries its value at the tip. */
export function BarChart({ title, caption, data, valueLabel }: { title: string; caption?: string; data: Datum[]; valueLabel: string }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ChartFrame title={title} caption={caption} data={data} valueLabel={valueLabel}>
      <ul className="space-y-2">
        {data.map((d, i) => (
          <li key={d.label} className="grid grid-cols-[7rem_1fr] items-center gap-2 text-sm">
            <span className="truncate text-slate-600">{d.label}</span>
            <button
              type="button"
              aria-label={`${d.label}: ${d.value} ${valueLabel.toLowerCase()}`}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              className="flex h-6 items-center gap-2 border-l"
              style={{ borderColor: "var(--viz-baseline)" }}
            >
              <span className="block h-3 rounded-r" style={{ width: `${(d.value / max) * 85}%`, minWidth: d.value > 0 ? 3 : 0, backgroundColor: "var(--viz-series-1)", opacity: active === null || active === i ? 1 : 0.55 }} />
              <span className="text-xs tabular-nums text-slate-700">{d.value}</span>
            </button>
          </li>
        ))}
      </ul>
    </ChartFrame>
  );
}
