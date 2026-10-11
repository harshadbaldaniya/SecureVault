import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { api, ApiError } from "@/services/api";
import type { AnomalyAlert, Page } from "@/types/api";

const PAGE_SIZE = 25;
const SEVERITY_TONE = { LOW: "slate", MEDIUM: "amber", HIGH: "red" } as const;
const STATUS_TONE = { OPEN: "red", ACKNOWLEDGED: "amber", DISMISSED: "slate" } as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function AlertsPage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("OPEN");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);
  const [reviewing, setReviewing] = useState<{ alert: AnomalyAlert; verdict: "acknowledge" | "dismiss" } | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const params = { status: status || undefined, severity: severity || undefined, page };
  const query = useQuery({ queryKey: ["alerts", params], queryFn: () => api.get<Page<AnomalyAlert>>("/alerts/", params), placeholderData: (p) => p });
  const review = useMutation({
    mutationFn: () => api.post(`/alerts/${reviewing?.alert.id}/${reviewing?.verdict}/`, { note }),
    onSuccess: async () => {
      setReviewing(null);
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (e) => setError(message(e)),
  });

  return (
    <>
      <PageHeader title="Security alerts" description="Raised by transparent rules (new device, unfamiliar network, reveal bursts, untrusted-device blocks). They are signals to review, not proof of an attack." />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-44">
          <Field label="Status">
            {(props) => (
              <Select {...props} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
                <option value="OPEN">Open</option>
                <option value="ACKNOWLEDGED">Acknowledged</option>
                <option value="DISMISSED">Dismissed</option>
                <option value="">All</option>
              </Select>
            )}
          </Field>
        </div>
        <div className="w-44">
          <Field label="Severity">
            {(props) => (
              <Select {...props} value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}>
                <option value="">All</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </Select>
            )}
          </Field>
        </div>
      </div>

      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{message(query.error)}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title="No alerts match" />
      ) : (
        <>
          <Table caption="Security alerts" headers={["When", "Alert", "Person", "Severity", "Status", "Actions"]}>
            {query.data.results.map((a) => (
              <tr key={a.id} className="align-top">
                <td className="whitespace-nowrap px-4 py-3">{new Date(a.created_at).toLocaleString()}</td>
                <td className="px-4 py-3">
                  {a.summary}
                  {a.ip_address && <span className="block font-mono text-xs text-slate-500">{a.ip_address}</span>}
                </td>
                <td className="px-4 py-3">{a.user_name}</td>
                <td className="px-4 py-3">
                  <Badge tone={SEVERITY_TONE[a.severity]}>{a.severity.toLowerCase()}</Badge>
                </td>
                <td className="px-4 py-3">
                  <Badge tone={STATUS_TONE[a.status]}>{a.status.toLowerCase()}</Badge>
                  {a.review_note && <span className="block text-xs text-slate-500">{a.review_note}</span>}
                </td>
                <td className="space-x-1 whitespace-nowrap px-4 py-3">
                  {a.status === "OPEN" && (
                    <>
                      <Button variant="ghost" onClick={() => { setError(null); setReviewing({ alert: a, verdict: "acknowledge" }); }} aria-label={`Acknowledge: ${a.summary}`}>
                        Acknowledge
                      </Button>
                      <Button variant="ghost" onClick={() => { setError(null); setReviewing({ alert: a, verdict: "dismiss" }); }} aria-label={`Dismiss: ${a.summary}`}>
                        Dismiss
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={reviewing !== null} title={reviewing?.verdict === "dismiss" ? "Dismiss alert" : "Acknowledge alert"} onClose={() => setReviewing(null)}>
        <div className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <p className="text-sm text-slate-600">{reviewing?.alert.summary}</p>
          <Field label="Review note (recorded in the audit log)">{(props) => <Input {...props} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}</Field>
          <div className="flex justify-end">
            <Button loading={review.isPending} onClick={() => review.mutate()}>
              {reviewing?.verdict === "dismiss" ? "Dismiss" : "Acknowledge"}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
