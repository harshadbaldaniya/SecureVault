import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { Alert, Badge, Button, Card, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { api, ApiError } from "@/services/api";
import type { AuditEntry, ChainVerification, Page } from "@/types/api";

import { AUDIT_ACTIONS } from "./actions";
import { AuditDetails } from "./AuditDetails";

const PAGE_SIZE = 25;
const outcomeTone = { SUCCESS: "green", FAILURE: "red", DENIED: "amber" } as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function AuditPage() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [search, setSearch] = useState("");
  const [after, setAfter] = useState("");
  const [before, setBefore] = useState("");
  // The record whose details panel is open, and the button it hangs off (one panel at a time).
  const [open, setOpen] = useState<{ id: number; anchor: HTMLElement } | null>(null);
  const closeDetails = useCallback(() => setOpen(null), []);

  const params = {
    page,
    action,
    outcome,
    search,
    created_after: after ? new Date(`${after}T00:00:00`).toISOString() : "",
    created_before: before ? new Date(`${before}T23:59:59`).toISOString() : "",
  };
  const query = useQuery({
    queryKey: ["audit", params],
    queryFn: () => api.get<Page<AuditEntry>>("/audit-logs/", params),
    placeholderData: (previous) => previous,
  });

  const verify = useMutation({ mutationFn: () => api.get<ChainVerification>("/audit-logs/verify/") });
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1); closeDetails(); };

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Append-only record of security-relevant actions. Each entry is hash-chained to the one before it."
        actions={
          <Button variant="secondary" onClick={() => verify.mutate()} loading={verify.isPending}>
            Verify integrity
          </Button>
        }
      />

      {verify.isError && <Alert tone="error" className="mb-4">{message(verify.error)}</Alert>}
      {verify.data && (
        <Alert tone={verify.data.valid ? "success" : "error"} className="mb-4">
          {verify.data.valid
            ? `Integrity check passed: ${verify.data.checked} records verified in order.`
            : `Integrity check FAILED at record #${verify.data.broken_at_sequence}. The log may have been altered; escalate to your security team.`}
        </Alert>
      )}

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Action">
            {(props) => (
              <Select {...props} value={action} onChange={(e) => reset(setAction)(e.target.value)}>
                <option value="">All actions</option>
                {AUDIT_ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Outcome">
            {(props) => (
              <Select {...props} value={outcome} onChange={(e) => reset(setOutcome)(e.target.value)}>
                <option value="">All outcomes</option>
                <option value="SUCCESS">Success</option>
                <option value="FAILURE">Failure</option>
                <option value="DENIED">Denied</option>
              </Select>
            )}
          </Field>
          <Field label="Actor or target">{(props) => <Input {...props} type="search" value={search} onChange={(e) => reset(setSearch)(e.target.value)} placeholder="Email or name" />}</Field>
          <Field label="From">{(props) => <Input {...props} type="date" value={after} onChange={(e) => reset(setAfter)(e.target.value)} />}</Field>
          <Field label="To">{(props) => <Input {...props} type="date" value={before} onChange={(e) => reset(setBefore)(e.target.value)} />}</Field>
        </div>
      </Card>

      <div className="mt-4">
        {query.isPending ? (
          <PageLoader />
        ) : query.isError ? (
          <Alert tone="error">{message(query.error)}</Alert>
        ) : query.data.results.length === 0 ? (
          <EmptyState title="No matching audit entries" hint="Try widening the filters." />
        ) : (
          <>
            <Table caption="Audit log" headers={["Time", "Action", "Outcome", "Actor", "Target", "IP", "Details"]}>
              {query.data.results.map((entry) => (
                <tr key={entry.id} className="align-top">
                  <td className="whitespace-nowrap px-4 py-3">
                    <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{entry.action}</td>
                  <td className="px-4 py-3">
                    <Badge tone={outcomeTone[entry.outcome]}>{entry.outcome}</Badge>
                  </td>
                  <td className="px-4 py-3">{entry.actor_email || "—"}</td>
                  <td className="px-4 py-3">
                    {entry.target_type || "—"}
                    {entry.target_label && <span className="block text-xs text-slate-500">{entry.target_label}</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{entry.ip_address ?? "—"}</td>
                  <td className="px-4 py-3">
                    <Button
                      variant="ghost"
                      aria-expanded={open?.id === entry.id}
                      aria-haspopup="dialog"
                      aria-controls={open?.id === entry.id ? `audit-details-${entry.id}` : undefined}
                      aria-label={`${open?.id === entry.id ? "Hide" : "Show"} details for record #${entry.sequence}`}
                      onClick={(event) => setOpen(open?.id === entry.id ? null : { id: entry.id, anchor: event.currentTarget })}
                    >
                      {open?.id === entry.id ? "Hide" : "Show"}
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={(next) => { closeDetails(); setPage(next); }} />
            {open && query.data.results.find((e) => e.id === open.id) && <AuditDetails entry={query.data.results.find((e) => e.id === open.id)!} anchor={open.anchor} onClose={closeDetails} />}
          </>
        )}
      </div>
    </>
  );
}
