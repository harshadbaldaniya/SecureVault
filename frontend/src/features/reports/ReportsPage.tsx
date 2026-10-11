import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { DownloadIcon } from "@/components/icons";
import { Alert, Button, Card, Checkbox, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table, LinkButton } from "@/components/ui";
import { AUDIT_ACTIONS } from "@/features/audit/actions";
import { DelegationTree } from "@/features/sharing/DelegationTree";
import { PersonPicker } from "@/features/sharing/ShareDialog";
import { api, ApiError, apiUrl, type QueryParams } from "@/services/api";
import type { DelegationTree as Tree, Department, Page, Person, ReportDefinition, ReportPage, ServiceItem } from "@/types/api";

const PAGE_SIZE = 50;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

interface FilterState {
  date_from: string;
  date_to: string;
  department: string;
  user: Person | null;
  service: string;
  action: string[];
  device_trust: string;
  share_status: string;
  status: string;
}
const EMPTY: FilterState = { date_from: "", date_to: "", department: "", user: null, service: "", action: [], device_trust: "", share_status: "", status: "" };

function daysAgo(days: number) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Only the filters this report supports are sent (the server rejects the others). */
function toParams(filters: FilterState, supported: readonly string[], columns: string[] | null): QueryParams {
  const has = (name: string) => supported.includes(name);
  return {
    date_from: has("date") ? filters.date_from : undefined,
    date_to: has("date") ? filters.date_to : undefined,
    department: has("department") ? filters.department : undefined,
    user: has("user") ? filters.user?.id : undefined,
    service: has("service") ? filters.service : undefined,
    action: has("action") ? filters.action : undefined,
    device_trust: has("device_trust") ? filters.device_trust : undefined,
    share_status: has("share_status") ? filters.share_status : undefined,
    status: has("status") ? filters.status : undefined,
    columns: columns?.join(","),
  };
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return new Date(value).toLocaleString();
  return String(value);
}

export function ReportsPage() {
  const catalog = useQuery({ queryKey: ["reports", "catalog"], queryFn: () => api.get<{ reports: ReportDefinition[] }>("/reports/") });
  const departments = useQuery({ queryKey: ["departments", "options"], queryFn: () => api.get<Page<Department>>("/departments/", { page_size: 100 }) });
  const services = useQuery({ queryKey: ["services", "options"], queryFn: () => api.get<Page<ServiceItem>>("/services/", { page_size: 100 }) });
  const [key, setKey] = useState("audit");
  const [filters, setFilters] = useState<FilterState>(EMPTY);
  const [chosen, setChosen] = useState<string[] | null>(null); // null = all columns
  const [page, setPage] = useState(1);
  const [treeFor, setTreeFor] = useState<string | null>(null);

  const report = catalog.data?.reports.find((r) => r.key === key);
  const supported = useMemo(() => report?.filters ?? [], [report]);
  const columns = chosen ?? report?.columns.map((c) => c.key) ?? [];
  const params = useMemo(() => toParams(filters, supported, chosen), [filters, supported, chosen]);

  const rows = useQuery({
    queryKey: ["reports", key, params, page],
    queryFn: () => api.get<ReportPage>(`/reports/${key}/`, { ...params, page, page_size: PAGE_SIZE }),
    enabled: Boolean(report),
    placeholderData: (p) => p,
  });
  const tree = useQuery({ queryKey: ["tree", treeFor], queryFn: () => api.get<Tree>(`/shares/tree/${treeFor}/`), enabled: Boolean(treeFor) });

  const set = <K extends keyof FilterState>(name: K, value: FilterState[K]) => {
    setFilters((f) => ({ ...f, [name]: value }));
    setPage(1);
  };
  const exportHref = (format: string) => apiUrl(`/reports/${key}/`, { ...params, format });

  if (catalog.isPending) return <PageLoader />;
  if (catalog.isError) return <Alert tone="error">{message(catalog.error)}</Alert>;

  return (
    <>
      <PageHeader title="Reports" description="Compliance and security reports. Metadata only: no secret ever appears in a report or export." />

      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200" role="tablist" aria-label="Reports">
        {catalog.data.reports.map((r) => (
          <button
            key={r.key}
            type="button"
            role="tab"
            aria-selected={key === r.key}
            onClick={() => {
              setKey(r.key);
              setFilters(EMPTY);
              setChosen(null);
              setPage(1);
            }}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${key === r.key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
          >
            {r.title}
          </button>
        ))}
      </div>
      {report && <p className="mb-4 text-sm text-slate-600">{report.description}</p>}

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          {supported.includes("date") && (
            <>
              <div className="w-40">
                <Field label="From">{(props) => <Input {...props} type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} />}</Field>
              </div>
              <div className="w-40">
                <Field label="To">{(props) => <Input {...props} type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} />}</Field>
              </div>
              <div className="flex gap-1 pb-1">
                {[7, 30, 90].map((d) => (
                  <Button key={d} variant="secondary" size="sm" onClick={() => { set("date_from", daysAgo(d - 1)); set("date_to", daysAgo(0)); }}>
                    Last {d} days
                  </Button>
                ))}
              </div>
            </>
          )}
          {supported.includes("department") && (
            <div className="w-48">
              <Field label="Department">
                {(props) => (
                  <Select {...props} value={filters.department} onChange={(e) => set("department", e.target.value)}>
                    <option value="">All</option>
                    {departments.data?.results.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          )}
          {supported.includes("service") && (
            <div className="w-48">
              <Field label="Service">
                {(props) => (
                  <Select {...props} value={filters.service} onChange={(e) => set("service", e.target.value)}>
                    <option value="">All</option>
                    {services.data?.results.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          )}
          {supported.includes("device_trust") && (
            <div className="w-40">
              <Field label="Device trust">
                {(props) => (
                  <Select {...props} value={filters.device_trust} onChange={(e) => set("device_trust", e.target.value)}>
                    <option value="">Any</option>
                    <option value="TRUSTED">Trusted</option>
                    <option value="PENDING">Pending</option>
                    <option value="SUSPENDED">Suspended</option>
                    <option value="REVOKED">Revoked</option>
                  </Select>
                )}
              </Field>
            </div>
          )}
          {supported.includes("share_status") && (
            <div className="w-40">
              <Field label="Share status">
                {(props) => (
                  <Select {...props} value={filters.share_status} onChange={(e) => set("share_status", e.target.value)}>
                    <option value="">Any</option>
                    <option value="active">Active</option>
                    <option value="expired">Expired</option>
                    <option value="revoked">Revoked</option>
                    <option value="consumed">View-once used</option>
                  </Select>
                )}
              </Field>
            </div>
          )}
          {supported.includes("status") && report && report.statuses.length > 0 && (
            <div className="w-40">
              <Field label="Status">
                {(props) => (
                  <Select {...props} value={filters.status} onChange={(e) => set("status", e.target.value)}>
                    <option value="">Any</option>
                    {report.statuses.map((s) => (
                      <option key={s} value={s}>
                        {s.toLowerCase()}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          )}
        </div>
        {supported.includes("user") && (
          <div className="mt-3 max-w-md">
            <PersonPicker selected={filters.user} onSelect={(p) => set("user", p)} label="Person" />
          </div>
        )}
        {supported.includes("action") && (
          <details className="mt-3">
            <summary className="cursor-pointer text-sm text-slate-700">Actions ({filters.action.length ? filters.action.length : "all"})</summary>
            <div className="mt-2 grid grid-cols-2 gap-1 sm:grid-cols-4">
              {AUDIT_ACTIONS.map((a) => (
                <Checkbox key={a} label={a} checked={filters.action.includes(a)} onChange={() => set("action", filters.action.includes(a) ? filters.action.filter((x) => x !== a) : [...filters.action, a])} />
              ))}
            </div>
          </details>
        )}
        {report && (
          <details className="mt-3">
            <summary className="cursor-pointer text-sm text-slate-700">Columns ({columns.length} of {report.columns.length}): custom report builder</summary>
            <div className="mt-2 grid grid-cols-2 gap-1 sm:grid-cols-4">
              {report.columns.map((c) => (
                <Checkbox
                  key={c.key}
                  label={c.label}
                  checked={columns.includes(c.key)}
                  onChange={() => {
                    const next = columns.includes(c.key) ? columns.filter((k) => k !== c.key) : [...columns, c.key];
                    setChosen(next.length ? next : null);
                    setPage(1);
                  }}
                />
              ))}
            </div>
          </details>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-600">Export:</span>
          {[["csv", "CSV"], ["xlsx", "Excel"], ["pdf", "PDF"]].map(([format, label]) => (
            <LinkButton key={format} href={exportHref(format as string)} size="sm" download>
              <DownloadIcon />
              {label}
            </LinkButton>
          ))}
          <span className="text-xs text-slate-500">Exports are recorded in the audit log and capped at 10,000 rows (PDF: 2,000).</span>
        </div>
      </Card>

      <div className={`mt-4 ${rows.isFetching ? "opacity-60" : ""}`}>
        {rows.isPending ? (
          <PageLoader />
        ) : rows.isError ? (
          <Alert tone="error">{message(rows.error)}</Alert>
        ) : rows.data.results.length === 0 ? (
          <EmptyState title="No rows match these filters" />
        ) : (
          <>
            <p className="mb-2 text-sm text-slate-600">{rows.data.count.toLocaleString()} rows</p>
            <Table caption={rows.data.title} headers={[...rows.data.columns.map((c) => c.label), ...(key === "shares" ? ["Tree"] : [])]}>
              {rows.data.results.map((row, i) => (
                <tr key={i} className="align-top">
                  {rows.data.columns.map((c) => (
                    <td key={c.key} className="px-4 py-2">
                      {cellText(row[c.key])}
                    </td>
                  ))}
                  {key === "shares" && (
                    <td className="px-4 py-2">
                      {row.credential_id && (
                        <Button variant="ghost" size="sm" onClick={() => setTreeFor(String(row.credential_id))}>
                          View tree
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} count={rows.data.count} onPage={setPage} />
          </>
        )}
      </div>

      <Dialog open={treeFor !== null} title={tree.data ? `Delegation tree: ${tree.data.credential_title}` : "Delegation tree"} onClose={() => setTreeFor(null)}>
        {tree.isPending ? <PageLoader /> : tree.isError ? <Alert tone="error">{message(tree.error)}</Alert> : <DelegationTree owner={tree.data.owner} nodes={tree.data.nodes} />}
        <div className="mt-4 flex justify-end">
          <Button variant="secondary" onClick={() => setTreeFor(null)}>
            Close
          </Button>
        </div>
      </Dialog>
    </>
  );
}
