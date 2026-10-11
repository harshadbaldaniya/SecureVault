import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, Checkbox, ConfirmDialog, Field, Input, Select } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { api, ApiError } from "@/services/api";
import type { Credential, DelegationTree as Tree, Page, Person, SecurityPolicy, SharePermission, TreeNode } from "@/types/api";

import { DelegationTree, PERMISSION_TEXT } from "./DelegationTree";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function PersonPicker({ selected, onSelect, label = "Share with" }: { selected: Person | null; onSelect: (p: Person | null) => void; label?: string }) {
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search);
  const people = useQuery({
    queryKey: ["people", debounced],
    queryFn: () => api.get<Page<Person>>("/people/", { search: debounced, page_size: 10 }),
    enabled: debounced.trim().length >= 2,
  });

  if (selected) {
    return (
      <div className="flex items-center justify-between rounded-md border border-slate-300 px-3 py-2 text-sm">
        <span>
          <strong>{selected.full_name}</strong> <span className="text-slate-500">{selected.email}</span>
        </span>
        <Button variant="ghost" size="sm" onClick={() => onSelect(null)}>
          Change
        </Button>
      </div>
    );
  }
  return (
    <div>
      <Field label={label} hint="Type at least 2 letters of a name or email.">
        {(props) => <Input {...props} type="search" value={search} onChange={(e) => setSearch(e.target.value)} autoComplete="off" />}
      </Field>
      {people.data && (
        <ul className="mt-1 max-h-48 overflow-auto rounded-md border border-slate-200" aria-label="Matching people">
          {people.data.results.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">No matching colleagues.</li>}
          {people.data.results.map((p) => (
            <li key={p.id}>
              <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-slate-50" onClick={() => onSelect(p)}>
                <span className="font-medium">{p.full_name}</span> <span className="text-slate-500">{p.email}</span>
                {p.department_name && <span className="block text-xs text-slate-400">{p.department_name}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ShareDialogContent({ credential, onDone }: { credential: Credential; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [person, setPerson] = useState<Person | null>(null);
  const [permission, setPermission] = useState<SharePermission>("VIEW");
  const [expires, setExpires] = useState("");
  const [viewOnce, setViewOnce] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<TreeNode | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const policy = useQuery({ queryKey: ["policy"], queryFn: () => api.get<SecurityPolicy>("/policy/") });
  const tree = useQuery({ queryKey: ["tree", credential.id], queryFn: () => api.get<Tree>(`/shares/tree/${credential.id}/`) });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["tree", credential.id] });
    await queryClient.invalidateQueries({ queryKey: ["shares"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api.post(`/vault/credentials/${credential.id}/share/`, {
        grantee: person?.id,
        permission: viewOnce ? "VIEW" : permission,
        is_view_once: viewOnce,
        expires_at: expires ? new Date(expires).toISOString() : null,
      }),
    onSuccess: async () => {
      setSuccess(`Shared with ${person?.full_name}. They have been notified.`);
      setPerson(null);
      setViewOnce(false);
      setExpires("");
      await refresh();
    },
    onError: (e) => setError(message(e)),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.post<{ revoked: number }>(`/shares/${id}/revoke/`),
    onSuccess: async (result) => {
      setRevoking(null);
      setSuccess(`Access revoked (${result.revoked} grant${result.revoked === 1 ? "" : "s"} including everything delegated from it).`);
      await refresh();
    },
    onError: (e) => setRevokeError(message(e)),
  });

  const canShare = credential.permissions.includes("SHARE");
  const maxDays = policy.data?.max_share_duration_days ?? 30;

  return (
    <div className="space-y-6">
      {success && <Alert tone="success">{success}</Alert>}
      {canShare ? (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            setSuccess(null);
            if (!person) return setError("Choose who to share with.");
            create.mutate();
          }}
        >
          {error && <Alert tone="error">{error}</Alert>}
          <PersonPicker selected={person} onSelect={setPerson} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Access level" hint={viewOnce ? "View-once shares are always view-only." : "Share lets them delegate to others, within your own limits."}>
              {(props) => (
                <Select {...props} value={viewOnce ? "VIEW" : permission} disabled={viewOnce} onChange={(e) => setPermission(e.target.value as SharePermission)}>
                  {(["VIEW", "EDIT", "SHARE"] as const).map((p) => (
                    <option key={p} value={p}>
                      {PERMISSION_TEXT[p]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Expires" hint={`Optional. At most ${maxDays} days, and never later than your own access.`}>
              {(props) => <Input {...props} type="datetime-local" value={expires} onChange={(e) => setExpires(e.target.value)} />}
            </Field>
          </div>
          {policy.data?.allow_view_once && (
            <div>
              <Checkbox label="View once (the secret can be revealed a single time)" checked={viewOnce} onChange={() => setViewOnce((v) => !v)} />
              <p className="ml-6 mt-1 text-xs text-slate-500">View-once limits how often SecureVault shows the secret. It cannot stop screenshots, photos or manual copying.</p>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onDone}>
              Close
            </Button>
            <Button type="submit" loading={create.isPending}>
              Share
            </Button>
          </div>
        </form>
      ) : (
        <Alert tone="info">You can see who has access but not share this credential further.</Alert>
      )}

      <section aria-labelledby="tree-heading">
        <h3 id="tree-heading" className="mb-2 text-sm font-semibold">
          Who has access
        </h3>
        {tree.isPending ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : tree.isError ? (
          <Alert tone="error">{message(tree.error)}</Alert>
        ) : (
          <DelegationTree owner={tree.data.owner} nodes={tree.data.nodes} onRevoke={(node) => { setRevokeError(null); setRevoking(node); }} />
        )}
      </section>

      <ConfirmDialog
        open={revoking !== null}
        title="Revoke access"
        danger
        confirmLabel="Revoke"
        busy={revoke.isPending}
        error={revokeError}
        message={<>Revoke access for <strong>{revoking?.grantee}</strong>? Everyone they shared it with loses access too, immediately.</>}
        onCancel={() => setRevoking(null)}
        onConfirm={() => revoking && revoke.mutate(revoking.id)}
      />
    </div>
  );
}
