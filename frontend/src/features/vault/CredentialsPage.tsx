import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { api, ApiError } from "@/services/api";
import type { Credential, Page, ServiceItem } from "@/types/api";

import { ShareDialogContent } from "@/features/sharing/ShareDialog";

import { CredentialForm } from "./CredentialForm";
import { ClipboardNotice, HygieneBadges, SecretDialog } from "./SecretWidgets";
import { useSecretActions } from "./useSecretActions";

const PAGE_SIZE = 25;
type StatusFilter = "" | "expiring" | "expired" | "reused";
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function CredentialsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [archived, setArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [service, setService] = useState("");
  const [tag, setTag] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");
  const [scope, setScope] = useState<"" | "mine" | "shared">("");
  const [sharing, setSharing] = useState<Credential | null>(null);
  const debouncedSearch = useDebounced(search);
  const debouncedTag = useDebounced(tag);
  const [editing, setEditing] = useState<Credential | "new" | null>(null);
  const [archiving, setArchiving] = useState<Credential | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const secrets = useSecretActions("credentials", "password");

  const services = useQuery({
    queryKey: ["services", "options"],
    queryFn: () => api.get<Page<ServiceItem>>("/services/", { page_size: 100, status: "ACTIVE" }),
  });

  const params = {
    page,
    archived: archived || undefined,
    scope: scope || undefined,
    search: debouncedSearch,
    service,
    tag: debouncedTag,
    expired: status === "expired" ? true : undefined,
    expiring_within_days: status === "expiring" ? 30 : undefined,
    reused: status === "reused" ? true : undefined,
  };
  const query = useQuery({
    queryKey: ["credentials", params],
    queryFn: () => api.get<Page<Credential>>("/vault/credentials/", params),
    placeholderData: (previous) => previous,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["credentials"] });
  const archive = useMutation({
    mutationFn: (id: string) => api.delete(`/vault/credentials/${id}/`),
    onSuccess: async () => {
      setArchiving(null);
      await invalidate();
    },
    onError: (e) => setActionError(message(e)),
  });
  const restore = useMutation({
    mutationFn: (id: string) => api.post(`/vault/credentials/${id}/restore/`),
    onSuccess: invalidate,
    onError: (e) => setActionError(message(e)),
  });

  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };
  const error = secrets.error ?? actionError;

  return (
    <>
      <PageHeader
        title="Credentials"
        description="Passwords and API keys, encrypted with AES-256-GCM before they are stored. Only you can see your entries unless you share them."
        actions={!archived && <Button onClick={() => setEditing("new")}>New credential</Button>}
      />

      <ClipboardNotice state={secrets.clipboard} onDismiss={secrets.dismissClipboard} />
      {error && !archiving && (
        <Alert tone="error" className="mb-4">
          {error}
        </Alert>
      )}

      <div className="mb-4 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Credential views">
        {[false, true].map((value) => (
          <button
            key={String(value)}
            type="button"
            role="tab"
            aria-selected={archived === value}
            onClick={() => reset(setArchived)(value)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${archived === value ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
          >
            {value ? "Archived" : "Active"}
          </button>
        ))}
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Show">
          {(props) => (
            <Select {...props} value={scope} onChange={(e) => reset(setScope)(e.target.value as "" | "mine" | "shared")}>
              <option value="">Mine and shared with me</option>
              <option value="mine">Only mine</option>
              <option value="shared">Shared with me</option>
            </Select>
          )}
        </Field>
        <Field label="Search" hint="Title, username, service or category. Secrets are never searchable.">
          {(props) => <Input {...props} type="search" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />}
        </Field>
        <Field label="Service">
          {(props) => (
            <Select {...props} value={service} onChange={(e) => reset(setService)(e.target.value)}>
              <option value="">All services</option>
              {services.data?.results.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Tag">{(props) => <Input {...props} value={tag} onChange={(e) => reset(setTag)(e.target.value)} placeholder="e.g. prod" />}</Field>
        <Field label="Hygiene">
          {(props) => (
            <Select {...props} value={status} onChange={(e) => reset(setStatus)(e.target.value as StatusFilter)}>
              <option value="">All</option>
              <option value="expiring">Expiring within 30 days</option>
              <option value="expired">Expired</option>
              <option value="reused">Reused passwords</option>
            </Select>
          )}
        </Field>
      </div>

      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{message(query.error)}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title={archived ? "No archived credentials" : "No credentials found"} hint={archived ? undefined : "Add your first credential, or change the filters."} />
      ) : (
        <>
          <Table caption="Credentials" headers={["Title", "Service", "Hygiene", "Expires", "Tags", "Actions"]}>
            {query.data.results.map((c) => {
              const can = (p: string) => c.permissions.includes(p as never);
              const busy = secrets.busyId === c.id;
              return (
                <tr key={c.id}>
                  <td className="px-4 py-3">
                    <span className="font-medium">{c.title}</span>
                    {c.username && <span className="block text-xs text-slate-500">{c.username}</span>}
                    {c.sharing && (
                      <span className="mt-1 flex flex-wrap items-center gap-1 text-xs text-slate-500">
                        <Badge tone="blue">Shared by {c.sharing.shared_by ?? c.owner_name}</Badge>
                        {c.sharing.view_once && <Badge tone="amber">View once</Badge>}
                        {c.sharing.consumed && <Badge tone="slate">View-once used</Badge>}
                        {c.sharing.expires_at && <span>until {new Date(c.sharing.expires_at).toLocaleString()}</span>}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">{c.service_name ?? "—"}</td>
                  <td className="px-4 py-3">
                    <HygieneBadges credential={c} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">{c.expires_at ?? "Never"}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {c.tags.map((t) => (
                        <Badge key={t}>{t}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="space-x-1 whitespace-nowrap px-4 py-3">
                    {archived ? (
                      can("EDIT") && (
                        <Button variant="ghost" onClick={() => restore.mutate(c.id)} aria-label={`Restore ${c.title}`}>
                          Restore
                        </Button>
                      )
                    ) : (
                      <>
                        {can("REVEAL") && (
                          <Button variant="ghost" disabled={busy} onClick={() => void secrets.reveal(c.id, c.title)} aria-label={`Reveal ${c.title}`}>
                            Reveal
                          </Button>
                        )}
                        {can("COPY") && (
                          <Button variant="ghost" disabled={busy} onClick={() => void secrets.copy(c.id)} aria-label={`Copy ${c.title}`}>
                            Copy
                          </Button>
                        )}
                        {can("EDIT") && (
                          <Button variant="ghost" onClick={() => setEditing(c)} aria-label={`Edit ${c.title}`}>
                            Edit
                          </Button>
                        )}
                        {can("SHARE") && (
                          <Button variant="ghost" onClick={() => setSharing(c)} aria-label={`Share ${c.title}`}>
                            Share
                          </Button>
                        )}
                        {can("DELETE") && (
                          <Button variant="danger-ghost" onClick={() => { setActionError(null); setArchiving(c); }} aria-label={`Archive ${c.title}`}>
                            Archive
                          </Button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={editing !== null} title={editing === "new" ? "New credential" : "Edit credential"} onClose={() => setEditing(null)}>
        {editing !== null && <CredentialForm credential={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Dialog>

      <SecretDialog title={secrets.revealed ? `Secret for ${secrets.revealed.title}` : ""} secret={secrets.revealed?.value ?? null} onClose={secrets.closeReveal} />

      <Dialog open={sharing !== null} title={sharing ? `Share "${sharing.title}"` : ""} onClose={() => setSharing(null)}>
        {sharing && <ShareDialogContent credential={sharing} onDone={() => setSharing(null)} />}
      </Dialog>

      <ConfirmDialog
        open={archiving !== null}
        title="Archive credential"
        danger
        confirmLabel="Archive"
        busy={archive.isPending}
        error={actionError}
        message={<>Archive <strong>{archiving?.title}</strong>? It disappears from the active list and can be restored for 30 days, after which it is permanently deleted.</>}
        onCancel={() => setArchiving(null)}
        onConfirm={() => archiving && archive.mutate(archiving.id)}
      />
    </>
  );
}
