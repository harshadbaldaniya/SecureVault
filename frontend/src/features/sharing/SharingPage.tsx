import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, ConfirmDialog, EmptyState, Field, PageHeader, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { api, ApiError } from "@/services/api";
import type { Page, Share, ShareState } from "@/types/api";

import { PERMISSION_TEXT, STATE_TONE } from "./DelegationTree";

const PAGE_SIZE = 25;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function SharingPage() {
  const queryClient = useQueryClient();
  const [direction, setDirection] = useState<"given" | "received">("given");
  const [state, setState] = useState<"" | Lowercase<ShareState>>("active");
  const [page, setPage] = useState(1);
  const [revoking, setRevoking] = useState<Share | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const params = { direction, state: state || undefined, page };
  const query = useQuery({
    queryKey: ["shares", params],
    queryFn: () => api.get<Page<Share>>("/shares/", params),
    placeholderData: (previous) => previous,
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.post<{ revoked: number }>(`/shares/${id}/revoke/`),
    onSuccess: async (result) => {
      setRevoking(null);
      setNotice(`Revoked ${result.revoked} grant${result.revoked === 1 ? "" : "s"}, including everything delegated from it.`);
      await queryClient.invalidateQueries({ queryKey: ["shares"] });
    },
    onError: (e) => setRevokeError(message(e)),
  });

  return (
    <>
      <PageHeader title="Sharing" description="Access you have given to others and access others have given you." />
      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div role="tablist" aria-label="Direction" className="flex gap-1 border-b border-slate-200">
          {(["given", "received"] as const).map((d) => (
            <button
              key={d}
              type="button"
              role="tab"
              aria-selected={direction === d}
              onClick={() => { setDirection(d); setPage(1); }}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${direction === d ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
            >
              {d === "given" ? "Shared by me" : "Shared with me"}
            </button>
          ))}
        </div>
        <div className="w-48">
          <Field label="Status">
            {(props) => (
              <Select {...props} value={state} onChange={(e) => { setState(e.target.value as typeof state); setPage(1); }}>
                <option value="active">Active</option>
                <option value="expired">Expired</option>
                <option value="revoked">Revoked</option>
                <option value="consumed">View-once used</option>
                <option value="">All</option>
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
        <EmptyState title="Nothing here" hint={direction === "given" ? "Share a credential from the Credentials page." : "When someone shares a credential with you it appears here."} />
      ) : (
        <>
          <Table caption="Share grants" headers={["Credential", direction === "given" ? "Shared with" : "Shared by", "Access", "Status", "Expires", "Actions"]}>
            {query.data.results.map((s) => {
              const other = direction === "given" ? s.grantee : s.grantor;
              return (
                <tr key={s.id}>
                  <td className="px-4 py-3 font-medium">{s.credential_title}</td>
                  <td className="px-4 py-3">
                    {other.full_name}
                    <span className="block text-xs text-slate-500">{other.email}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      <Badge tone="blue">{PERMISSION_TEXT[s.permission]}</Badge>
                      {s.is_view_once && <Badge tone="amber">View once</Badge>}
                      {s.depth > 0 && <Badge>Delegated (level {s.depth})</Badge>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={STATE_TONE[s.state]}>{s.state.toLowerCase()}</Badge>
                    {s.revoke_reason === "cascade" && <span className="block text-xs text-slate-500">upstream grant revoked</span>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">{new Date(s.expires_at).toLocaleString()}</td>
                  <td className="px-4 py-3">
                    {s.state === "ACTIVE" && direction === "given" && (
                      <Button variant="ghost" className="text-red-700" onClick={() => { setRevokeError(null); setRevoking(s); }} aria-label={`Revoke ${s.grantee.full_name}'s access to ${s.credential_title}`}>
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

      <ConfirmDialog
        open={revoking !== null}
        title="Revoke access"
        danger
        confirmLabel="Revoke"
        busy={revoke.isPending}
        error={revokeError}
        message={<>Revoke <strong>{revoking?.grantee.full_name}</strong>'s access to <strong>{revoking?.credential_title}</strong>? Anyone they delegated to loses access too.</>}
        onCancel={() => setRevoking(null)}
        onConfirm={() => revoking && revoke.mutate(revoking.id)}
      />
    </>
  );
}
