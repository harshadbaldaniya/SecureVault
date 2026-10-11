import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table, Textarea, tabClass, tabListClass } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { AccessRequest, DirectoryEntry, Page, RequestState, SecurityPolicy } from "@/types/api";

const PAGE_SIZE = 25;
type Tab = "request" | "mine" | "to_approve";
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
const STATE_TONE: Record<RequestState, "blue" | "green" | "red" | "slate" | "amber"> = {
  PENDING: "blue",
  APPROVED: "green",
  REJECTED: "red",
  CANCELLED: "slate",
  EXPIRED: "slate",
};

function RequestForm({ entry, onDone }: { entry: DirectoryEntry; onDone: (msg: string) => void }) {
  const queryClient = useQueryClient();
  const policy = useQuery({ queryKey: ["policy"], queryFn: () => api.get<SecurityPolicy>("/policy/") });
  const maxHours = (policy.data?.max_share_duration_days ?? 30) * 24;
  const [permission, setPermission] = useState<"VIEW" | "EDIT">("VIEW");
  const [hours, setHours] = useState("8");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => api.post("/access-requests/", { credential: entry.id, permission, duration_hours: Number(hours), reason }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["access-requests"] });
      onDone(`Request sent to ${entry.owner_name}.`);
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      if (Object.keys(fields).length) setErrors(fields);
      else setError(message(e));
    },
  });

  const validate = () => {
    const found: Record<string, string> = {};
    const n = Number(hours);
    if (!Number.isInteger(n) || n < 1 || n > maxHours) found.duration_hours = `Enter whole hours between 1 and ${maxHours}.`;
    if (reason.trim().length < 5) found.reason = "Explain why you need access (at least 5 characters).";
    setErrors(found);
    return Object.keys(found).length === 0;
  };

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        if (validate()) submit.mutate();
      }}
    >
      {error && <Alert tone="error">{error}</Alert>}
      <p className="text-sm text-slate-600">
        <strong>{entry.title}</strong> · owned by {entry.owner_name}
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Access level">
          {(props) => (
            <Select {...props} value={permission} onChange={(e) => setPermission(e.target.value as "VIEW" | "EDIT")}>
              <option value="VIEW">View</option>
              <option value="EDIT">Edit</option>
            </Select>
          )}
        </Field>
        <Field label="For how many hours" error={errors.duration_hours}>
          {(props) => <Input {...props} type="number" min={1} max={maxHours} value={hours} onChange={(e) => setHours(e.target.value)} />}
        </Field>
      </div>
      <Field label="Reason" error={errors.reason}>
        {(props) => <Textarea {...props} className="min-h-20 font-sans" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
      <div className="flex justify-end">
        <Button type="submit" loading={submit.isPending}>
          Send request
        </Button>
      </div>
    </form>
  );
}

function Decide({ request, onDone }: { request: AccessRequest; onDone: (msg: string) => void }) {
  const queryClient = useQueryClient();
  const [hours, setHours] = useState(String(request.requested_duration_hours));
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const decide = useMutation({
    mutationFn: (verdict: "approve" | "reject") =>
      api.post(`/access-requests/${request.id}/${verdict}/`, verdict === "approve" ? { duration_hours: Number(hours) } : { note }),
    onSuccess: async (_data, verdict) => {
      await queryClient.invalidateQueries({ queryKey: ["access-requests"] });
      onDone(verdict === "approve" ? `Approved. ${request.requester_name} has been notified.` : "Request declined.");
    },
    onError: (e) => setError(message(e)),
  });

  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <dl className="space-y-1 text-sm">
        <div>
          <dt className="inline text-slate-500">Requester: </dt>
          <dd className="inline">{request.requester_name}</dd>
        </div>
        <div>
          <dt className="inline text-slate-500">Asked for: </dt>
          <dd className="inline">
            {request.permission.toLowerCase()} for {request.requested_duration_hours} h
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Reason:</dt>
          <dd className="whitespace-pre-wrap">{request.reason}</dd>
        </div>
      </dl>
      <Field label="Grant for (hours)" hint={`Up to ${request.requested_duration_hours} h, as requested.`}>
        {(props) => <Input {...props} type="number" min={1} max={request.requested_duration_hours} value={hours} onChange={(e) => setHours(e.target.value)} />}
      </Field>
      <Field label="Note if declining (optional)">
        {(props) => <Input {...props} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="danger" loading={decide.isPending && decide.variables === "reject"} onClick={() => decide.mutate("reject")}>
          Decline
        </Button>
        <Button loading={decide.isPending && decide.variables === "approve"} onClick={() => decide.mutate("approve")}>
          Approve
        </Button>
      </div>
    </div>
  );
}

export function AccessRequestsPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("request");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search);
  const [requesting, setRequesting] = useState<DirectoryEntry | null>(null);
  const [deciding, setDeciding] = useState<AccessRequest | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const directory = useQuery({
    queryKey: ["directory", debounced, page],
    queryFn: () => api.get<Page<DirectoryEntry>>("/vault/directory/", { search: debounced, page }),
    enabled: tab === "request",
    placeholderData: (previous) => previous,
  });
  const requests = useQuery({
    queryKey: ["access-requests", tab, page],
    queryFn: () => api.get<Page<AccessRequest>>("/access-requests/", { box: tab, page }),
    enabled: tab !== "request",
    placeholderData: (previous) => previous,
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`/access-requests/${id}/cancel/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["access-requests"] }),
  });

  const done = (msg: string) => {
    setRequesting(null);
    setDeciding(null);
    setNotice(msg);
  };

  const tabs: Array<[Tab, string]> = [
    ["request", "Request access"],
    ["mine", "My requests"],
    ["to_approve", "To approve"],
  ];

  return (
    <>
      <PageHeader title="Access requests" description="Ask for time-limited access to a credential. Its owner approves or declines." />
      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}
      <div role="tablist" aria-label="Access request views" className={tabListClass}>
        {tabs.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => { setTab(value); setPage(1); }}
            className={tabClass(tab === value)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "request" ? (
        <>
          <div className="mb-4 w-full sm:w-80">
            <Field label="Search" hint="Only credentials whose owners allow requests are listed.">
              {(props) => <Input {...props} type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />}
            </Field>
          </div>
          {directory.isPending ? (
            <PageLoader />
          ) : directory.isError ? (
            <Alert tone="error">{message(directory.error)}</Alert>
          ) : directory.data.results.length === 0 ? (
            <EmptyState title="No requestable credentials found" />
          ) : (
            <>
              <Table caption="Requestable credentials" headers={["Credential", "Service", "Owner", "Actions"]}>
                {directory.data.results.map((entry) => (
                  <tr key={entry.id}>
                    <td className="px-4 py-3 font-medium">{entry.title}</td>
                    <td className="px-4 py-3">{entry.service_name ?? "—"}</td>
                    <td className="px-4 py-3">{entry.owner_name}</td>
                    <td className="px-4 py-3">
                      <Button variant="ghost" onClick={() => setRequesting(entry)} aria-label={`Request access to ${entry.title}`}>
                        Request access
                      </Button>
                    </td>
                  </tr>
                ))}
              </Table>
              <Pagination page={page} pageSize={PAGE_SIZE} count={directory.data.count} onPage={setPage} />
            </>
          )}
        </>
      ) : requests.isPending ? (
        <PageLoader />
      ) : requests.isError ? (
        <Alert tone="error">{message(requests.error)}</Alert>
      ) : requests.data.results.length === 0 ? (
        <EmptyState title={tab === "mine" ? "You have not requested access yet" : "Nothing waiting for your decision"} />
      ) : (
        <>
          <Table caption={tab === "mine" ? "My requests" : "Requests to approve"} headers={["Credential", tab === "mine" ? "Owner" : "Requester", "Asked for", "Status", "Actions"]}>
            {requests.data.results.map((r) => (
              <tr key={r.id}>
                <td className="px-4 py-3 font-medium">{r.credential_title}</td>
                <td className="px-4 py-3">{tab === "mine" ? r.owner_name : r.requester_name}</td>
                <td className="px-4 py-3">
                  {r.permission.toLowerCase()} · {r.requested_duration_hours} h
                </td>
                <td className="px-4 py-3">
                  <Badge tone={STATE_TONE[r.state]}>{r.state.toLowerCase()}</Badge>
                  {r.decision_note && <span className="block text-xs text-slate-500">{r.decision_note}</span>}
                </td>
                <td className="px-4 py-3">
                  {r.state === "PENDING" && tab === "mine" && (
                    <Button variant="ghost" onClick={() => cancel.mutate(r.id)} aria-label={`Cancel request for ${r.credential_title}`}>
                      Cancel
                    </Button>
                  )}
                  {r.state === "PENDING" && tab === "to_approve" && (
                    <Button variant="ghost" onClick={() => setDeciding(r)} aria-label={`Review request from ${r.requester_name}`}>
                      Review
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={requests.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={requesting !== null} title="Request access" onClose={() => setRequesting(null)}>
        {requesting && <RequestForm entry={requesting} onDone={done} />}
      </Dialog>
      <Dialog open={deciding !== null} title="Review access request" onClose={() => setDeciding(null)}>
        {deciding && <Decide request={deciding} onDone={done} />}
      </Dialog>
    </>
  );
}
