import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table, tabClass, tabListClass } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { api, ApiError } from "@/services/api";
import type { Device, DeviceEvent, Page, TrustState } from "@/types/api";

const PAGE_SIZE = 25;
const TRUST_TONE: Record<TrustState, "green" | "amber" | "red" | "slate"> = { TRUSTED: "green", PENDING: "amber", SUSPENDED: "red", REVOKED: "slate" };
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
type Operation = "approve" | "suspend" | "revoke";
const OPERATION_TEXT: Record<Operation, string> = { approve: "Approve (trust)", suspend: "Suspend", revoke: "Revoke" };

function TrustDialog({ device, operation, onDone }: { device: Device; operation: Operation; onDone: (msg: string) => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => api.post<Device>(`/devices/${device.id}/${operation}/`, { reason }),
    onSuccess: async (updated) => {
      await queryClient.invalidateQueries({ queryKey: ["devices"] });
      onDone(`"${updated.name}" is now ${updated.trust_state.toLowerCase()}.`);
    },
    onError: (e) => setError(message(e)),
  });
  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <p className="text-sm text-slate-600">
        {OPERATION_TEXT[operation]} <strong>{device.name}</strong> ({device.browser} on {device.os}) for {device.user_name}.
        {operation !== "approve" && " The device is signed out immediately."}
        {operation === "revoke" && " A revoked device must register again and be re-approved."}
      </p>
      {operation === "approve" && <Alert tone="info">Approve only after confirming with the person that this is their device (for example, in person or by phone).</Alert>}
      <Field label="Reason (recorded in the audit log)">{(props) => <Input {...props} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="flex justify-end">
        <Button variant={operation === "approve" ? "primary" : "danger"} loading={change.isPending} onClick={() => change.mutate()}>
          {OPERATION_TEXT[operation]}
        </Button>
      </div>
    </div>
  );
}

function ActivityDialog({ device }: { device: Device }) {
  const events = useQuery({ queryKey: ["devices", device.id, "events"], queryFn: () => api.get<DeviceEvent[]>(`/devices/${device.id}/events/`) });
  if (events.isPending) return <PageLoader />;
  if (events.isError) return <Alert tone="error">{message(events.error)}</Alert>;
  if (events.data.length === 0) return <p className="text-sm text-slate-500">No activity recorded.</p>;
  return (
    <ul className="max-h-96 space-y-2 overflow-auto text-sm" aria-label="Device activity">
      {events.data.map((e) => (
        <li key={e.id} className="rounded border border-slate-200 p-2">
          <span className="font-mono text-xs">{e.kind}</span> · <time dateTime={e.created_at}>{new Date(e.created_at).toLocaleString()}</time>
          {e.ip_address && <span className="text-slate-500"> · {e.ip_address}</span>}
          {Object.keys(e.details).length > 0 && <pre className="mt-1 overflow-x-auto text-xs text-slate-500">{JSON.stringify(e.details)}</pre>}
        </li>
      ))}
    </ul>
  );
}

export function DevicesPage() {
  const { user, can } = useAuth();
  const isAdmin = can("devices.manage");
  const queryClient = useQueryClient();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [trust, setTrust] = useState("");
  const [page, setPage] = useState(1);
  const [changing, setChanging] = useState<{ device: Device; operation: Operation } | null>(null);
  const [activity, setActivity] = useState<Device | null>(null);
  const [renaming, setRenaming] = useState<Device | null>(null);
  const [newName, setNewName] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const params = { scope: scope === "all" ? "all" : undefined, trust_state: trust || undefined, page };
  const query = useQuery({ queryKey: ["devices", params], queryFn: () => api.get<Page<Device>>("/devices/", params), placeholderData: (p) => p });
  const rename = useMutation({
    mutationFn: () => api.patch(`/devices/${renaming?.id}/`, { name: newName }),
    onSuccess: async () => {
      setRenaming(null);
      await queryClient.invalidateQueries({ queryKey: ["devices"] });
    },
  });

  return (
    <>
      <PageHeader title="Devices" description="Browsers and machines that have signed in to your account. Each is identified by a secure cookie; browser signals only help detect anomalies." />
      {notice && <Alert tone="success">{notice}</Alert>}

      {isAdmin && (
        <div role="tablist" aria-label="Device views" className={tabListClass}>
          {(["mine", "all"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={scope === value}
              onClick={() => { setScope(value); setPage(1); }}
              className={tabClass(scope === value)}
            >
              {value === "mine" ? "My devices" : "All devices"}
            </button>
          ))}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-48">
          <Field label="Trust">
            {(props) => (
              <Select {...props} value={trust} onChange={(e) => { setTrust(e.target.value); setPage(1); }}>
                <option value="">All states</option>
                <option value="PENDING">Pending approval</option>
                <option value="TRUSTED">Trusted</option>
                <option value="SUSPENDED">Suspended</option>
                <option value="REVOKED">Revoked</option>
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
        <EmptyState title="No devices" />
      ) : (
        <>
          <Table caption="Devices" headers={scope === "all" ? ["Device", "Person", "Trust", "Last seen", "Actions"] : ["Device", "Trust", "Last seen", "Actions"]}>
            {query.data.results.map((d) => {
              const own = d.user === user?.id;
              return (
                <tr key={d.id}>
                  <td className="px-4 py-3">
                    <span className="font-medium">{d.name}</span> {d.is_current && <Badge tone="blue">This device</Badge>}
                    <span className="block text-xs text-slate-500">
                      {d.browser} on {d.os}
                    </span>
                  </td>
                  {scope === "all" && (
                    <td className="px-4 py-3">
                      {d.user_name}
                      <span className="block text-xs text-slate-500">{d.user_email}</span>
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <Badge tone={TRUST_TONE[d.trust_state]}>{d.trust_state.toLowerCase()}</Badge>
                    {d.trust_reason && <span className="block text-xs text-slate-500">{d.trust_reason}</span>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "—"}
                    {d.last_ip && <span className="block font-mono text-xs text-slate-500">{d.last_ip}</span>}
                  </td>
                  <td className="space-x-1 whitespace-nowrap px-4 py-3">
                    <Button variant="ghost" onClick={() => setActivity(d)} aria-label={`Activity for ${d.name}`}>
                      Activity
                    </Button>
                    {own && d.trust_state !== "REVOKED" && (
                      <Button variant="ghost" onClick={() => { setRenaming(d); setNewName(d.name); }} aria-label={`Rename ${d.name}`}>
                        Rename
                      </Button>
                    )}
                    {isAdmin && !own && d.trust_state !== "TRUSTED" && d.trust_state !== "REVOKED" && (
                      <Button variant="ghost" onClick={() => setChanging({ device: d, operation: "approve" })} aria-label={`Approve ${d.name}`}>
                        Approve
                      </Button>
                    )}
                    {isAdmin && !own && d.trust_state === "TRUSTED" && (
                      <Button variant="danger-ghost" onClick={() => setChanging({ device: d, operation: "suspend" })} aria-label={`Suspend ${d.name}`}>
                        Suspend
                      </Button>
                    )}
                    {(isAdmin || own) && d.trust_state !== "REVOKED" && (
                      <Button variant="danger-ghost" onClick={() => setChanging({ device: d, operation: "revoke" })} aria-label={`Revoke ${d.name}`}>
                        Revoke
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={changing !== null} title={changing ? OPERATION_TEXT[changing.operation] : ""} onClose={() => setChanging(null)}>
        {changing && <TrustDialog device={changing.device} operation={changing.operation} onDone={(msg) => { setChanging(null); setNotice(msg); }} />}
      </Dialog>
      <Dialog open={activity !== null} title={activity ? `Activity: ${activity.name}` : ""} onClose={() => setActivity(null)}>
        {activity && <ActivityDialog device={activity} />}
      </Dialog>
      <Dialog open={renaming !== null} title="Rename device" onClose={() => setRenaming(null)}>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (newName.trim()) rename.mutate();
          }}
        >
          <Field label="Name">{(props) => <Input {...props} value={newName} maxLength={100} onChange={(e) => setNewName(e.target.value)} />}</Field>
          <div className="flex justify-end">
            <Button type="submit" loading={rename.isPending}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
