import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, ConfirmDialog, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Table, Textarea } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { PersonPicker } from "@/features/sharing/ShareDialog";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Lockdown, Page, Person } from "@/types/api";

const PAGE_SIZE = 25;
const MIN_REASON = 10;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function ReauthFields({ password, setPassword, code, setCode, mfa }: { password: string; setPassword: (v: string) => void; code: string; setCode: (v: string) => void; mfa: boolean }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Your password" hint="Required for this high-risk action.">
        {(props) => <Input {...props} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </Field>
      {mfa && (
        <Field label="Authenticator code">
          {(props) => <Input {...props} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />}
        </Field>
      )}
    </div>
  );
}

function ActivateForm({ onDone }: { onDone: (msg: string) => void }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [scope, setScope] = useState<"GLOBAL" | "USER">("GLOBAL");
  const [target, setTarget] = useState<Person | null>(null);
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const activate = useMutation({
    mutationFn: () => api.post<Lockdown>("/lockdown/activate/", { scope, target_user: scope === "USER" ? target?.id : null, reason, password, code }),
    gcTime: 0, // the request body contains the password: do not keep it in the mutation cache
    onSuccess: async (state) => {
      setConfirming(false);
      setPassword("");
      setCode("");
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["lockdown"] });
      onDone(`Lockdown active. ${state.terminated_session_count} session(s) were terminated.`);
    },
    onError: (e) => {
      setConfirming(false);
      setPassword("");
      setCode("");
      const fields = fieldErrors(e);
      if (Object.keys(fields).length) setErrors(fields);
      else setError(message(e));
    },
  });

  const validate = () => {
    const found: Record<string, string> = {};
    if (reason.trim().length < MIN_REASON) found.reason = `Describe the incident (at least ${MIN_REASON} characters).`;
    if (scope === "USER" && !target) found.target_user = "Choose the account to lock down.";
    if (!password) found.password = "Enter your password.";
    setErrors(found);
    return Object.keys(found).length === 0;
  };

  return (
    <Card title="Activate emergency lockdown" description="Takes effect immediately on the server. Connected clients are told within about a second.">
      <form
        noValidate
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          if (validate()) setConfirming(true);
        }}
      >
        {error && <Alert tone="error">{error}</Alert>}
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-slate-700">Scope</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="scope" checked={scope === "GLOBAL"} onChange={() => setScope("GLOBAL")} /> Whole organization
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="scope" checked={scope === "USER"} onChange={() => setScope("USER")} /> One account
            </label>
          </div>
        </fieldset>
        {scope === "USER" && (
          <div>
            <PersonPicker selected={target} onSelect={setTarget} label="Account to lock down" />
            {errors.target_user && <p role="alert" className="mt-1 text-xs text-red-700">{errors.target_user}</p>}
          </div>
        )}
        <Field label="Reason" hint="Visible to administrators and recorded in the audit log." error={errors.reason}>
          {(props) => <Textarea {...props} className="min-h-20 font-sans" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <ReauthFields password={password} setPassword={setPassword} code={code} setCode={setCode} mfa={Boolean(user?.mfa_enabled)} />
        {errors.password && <p role="alert" className="text-xs text-red-700">{errors.password}</p>}
        <div className="flex justify-end">
          <Button type="submit" variant="danger">
            Activate lockdown…
          </Button>
        </div>
      </form>
      <ConfirmDialog
        open={confirming}
        title="Confirm emergency lockdown"
        danger
        confirmLabel="Lock down now"
        busy={activate.isPending}
        message={
          scope === "GLOBAL" ? (
            <>Every employee is signed out and nobody, including administrators, can reveal, copy, edit or share secrets until the lockdown is lifted.</>
          ) : (
            <>
              <strong>{target?.full_name}</strong> is signed out everywhere and cannot sign in or use secrets until the lockdown is lifted.
            </>
          )
        }
        onCancel={() => setConfirming(false)}
        onConfirm={() => activate.mutate()}
      />
    </Card>
  );
}

function ResolveDialog({ lockdown, onDone }: { lockdown: Lockdown; onDone: (msg: string) => void }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const resolve = useMutation({
    mutationFn: () => api.post(`/lockdown/${lockdown.id}/resolve/`, { note, password, code }),
    gcTime: 0,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["lockdown"] });
      onDone("Lockdown lifted. Access is restored.");
    },
    onError: (e) => {
      setPassword("");
      setCode("");
      setError(message(e));
    },
  });
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        resolve.mutate();
      }}
    >
      {error && <Alert tone="error">{error}</Alert>}
      <p className="text-sm text-slate-600">Reason given: {lockdown.reason}</p>
      <Field label="Resolution note">{(props) => <Input {...props} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}</Field>
      <ReauthFields password={password} setPassword={setPassword} code={code} setCode={setCode} mfa={Boolean(user?.mfa_enabled)} />
      <div className="flex justify-end">
        <Button type="submit" loading={resolve.isPending}>
          Lift lockdown
        </Button>
      </div>
    </form>
  );
}

export function LockdownPage() {
  const queryClient = useQueryClient();
  const { refresh } = useAuth();
  const [page, setPage] = useState(1);
  const [resolving, setResolving] = useState<Lockdown | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const history = useQuery({ queryKey: ["lockdown", "history", page], queryFn: () => api.get<Page<Lockdown>>("/lockdown/", { page }), placeholderData: (p) => p });
  const active = history.data?.results.filter((l) => l.is_active) ?? [];

  const done = (msg: string) => {
    setResolving(null);
    setNotice(msg);
    void refresh();
    void queryClient.invalidateQueries({ queryKey: ["lockdown"] });
  };

  return (
    <>
      <PageHeader title="Emergency lockdown" description="Freeze access to secrets organization-wide or for one account. Enforced by the server on every request; WebSocket messages only inform clients." />
      {notice && <Alert tone="success">{notice}</Alert>}
      <div className="mt-4 space-y-6">
        {active.length > 0 && (
          <Card title="Active now">
            <ul className="space-y-3">
              {active.map((l) => (
                <li key={l.id} className="flex flex-wrap items-start justify-between gap-3 rounded-md bg-red-50 p-3 ring-1 ring-red-200">
                  <div className="text-sm">
                    <Badge tone="red">{l.scope === "GLOBAL" ? "Organization-wide" : `Account: ${l.target_user_name}`}</Badge>
                    <p className="mt-1">{l.reason}</p>
                    <p className="text-xs text-slate-700">
                      Started {new Date(l.triggered_at).toLocaleString()} by {l.initiated_by_name} · {l.terminated_session_count} session(s) terminated
                    </p>
                  </div>
                  <Button onClick={() => setResolving(l)}>Lift lockdown</Button>
                </li>
              ))}
            </ul>
          </Card>
        )}
        <ActivateForm onDone={done} />
        <Card title="History">
          {history.isPending ? (
            <PageLoader />
          ) : history.isError ? (
            <Alert tone="error">{message(history.error)}</Alert>
          ) : history.data.results.length === 0 ? (
            <EmptyState title="No lockdowns yet" />
          ) : (
            <>
              <Table caption="Lockdown history" headers={["Started", "Scope", "Reason", "Initiated by", "Sessions ended", "Resolution"]}>
                {history.data.results.map((l) => (
                  <tr key={l.id} className="align-top">
                    <td className="whitespace-nowrap px-4 py-3">{new Date(l.triggered_at).toLocaleString()}</td>
                    <td className="px-4 py-3">{l.scope === "GLOBAL" ? "Organization" : l.target_user_name}</td>
                    <td className="px-4 py-3">{l.reason}</td>
                    <td className="px-4 py-3">{l.initiated_by_name}</td>
                    <td className="px-4 py-3">{l.terminated_session_count}</td>
                    <td className="px-4 py-3">
                      {l.is_active ? (
                        <Badge tone="red">active</Badge>
                      ) : (
                        <>
                          <Badge tone="green">lifted</Badge>
                          <span className="block text-xs text-slate-500">
                            {l.resolved_at && new Date(l.resolved_at).toLocaleString()} by {l.resolved_by_name}
                            {l.resolution_note && `: ${l.resolution_note}`}
                          </span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </Table>
              <Pagination page={page} pageSize={PAGE_SIZE} count={history.data.count} onPage={setPage} />
            </>
          )}
        </Card>
      </div>
      <Dialog open={resolving !== null} title="Lift lockdown" onClose={() => setResolving(null)}>
        {resolving && <ResolveDialog lockdown={resolving} onDone={done} />}
      </Dialog>
    </>
  );
}
