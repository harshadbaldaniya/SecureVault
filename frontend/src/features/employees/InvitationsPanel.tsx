import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Field, Input, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Invitation, Page, Role } from "@/types/api";

import { INVITATION_LABEL, INVITATION_TONE, ROLE_LABEL } from "./labels";
import { useDepartmentOptions } from "./useDepartmentOptions";

const PAGE_SIZE = 25;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

const schema = z.object({
  email: z.string().trim().min(1, "Enter an email.").email("Enter a valid email address."),
  full_name: z.string().trim().min(1, "Enter a name.").max(150),
  role: z.enum(["ORG_ADMIN", "SEC_ADMIN", "EMPLOYEE"]),
  department: z.string(),
});
type FormValues = z.infer<typeof schema>;

function InviteForm({ onCreated, onClose }: { onCreated: (invitation: Invitation) => void; onClose: () => void }) {
  const departments = useDepartmentOptions();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { email: "", full_name: "", role: "EMPLOYEE", department: "" } });

  const invite = useMutation({
    mutationFn: (values: FormValues) => api.post<Invitation>("/invitations/", { ...values, department: values.department || null }),
    onSuccess: onCreated,
    onError: (e) => {
      if (e instanceof ApiError && e.code === "email_taken") return form.setError("email", { message: e.message });
      const fields = fieldErrors(e);
      const names = Object.keys(fields);
      if (names.length) names.forEach((n) => form.setError(n as keyof FormValues, { message: fields[n] ?? "Invalid value." }));
      else setError(message(e));
    },
  });

  return (
    <form onSubmit={form.handleSubmit((values) => { setError(null); invite.mutate(values); })} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <Field label="Work email" error={form.formState.errors.email?.message}>
        {(props) => <Input {...props} type="email" autoComplete="off" {...form.register("email")} />}
      </Field>
      <Field label="Full name" error={form.formState.errors.full_name?.message}>
        {(props) => <Input {...props} autoComplete="off" {...form.register("full_name")} />}
      </Field>
      <Field label="Role" error={form.formState.errors.role?.message}>
        {(props) => (
          <Select {...props} {...form.register("role")}>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Department" error={form.formState.errors.department?.message}>
        {(props) => (
          <Select {...props} {...form.register("department")}>
            <option value="">No department</option>
            {departments.data?.results.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={invite.isPending}>
          Create invitation
        </Button>
      </div>
    </form>
  );
}

export function InvitationsPanel() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<Invitation | null>(null);
  const [revoking, setRevoking] = useState<Invitation | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const query = useQuery({
    queryKey: ["invitations", page],
    queryFn: () => api.get<Page<Invitation>>("/invitations/", { page }),
    placeholderData: (previous) => previous,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["invitations"] });

  const resend = useMutation({
    mutationFn: (id: string) => api.post<Invitation>(`/invitations/${id}/resend/`),
    onSuccess: async (invitation) => {
      await refresh();
      setCopied(false);
      setLink(invitation);
    },
    onError: (e) => setActionError(message(e)),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.post(`/invitations/${id}/revoke/`),
    onSuccess: async () => {
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
      setRevoking(null);
    },
    onError: (e) => setActionError(message(e)),
  });

  const copy = async () => {
    if (!link?.invite_url) return;
    try {
      await navigator.clipboard.writeText(link.invite_url);
      setCopied(true);
    } catch {
      setCopied(false); // clipboard blocked: the field below can still be selected manually
    }
  };

  return (
    <>
      <div className="mb-4 flex justify-end">
        <Button onClick={() => setInviting(true)}>Invite employee</Button>
      </div>

      {actionError && !revoking && <Alert tone="error" className="mb-4">{actionError}</Alert>}

      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{message(query.error)}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title="No invitations yet" hint="Invite someone to create their account." />
      ) : (
        <>
          <Table caption="Invitations" headers={["Employee", "Role", "Status", "Expires", "Invited by", "Actions"]}>
            {query.data.results.map((i) => (
              <tr key={i.id}>
                <td className="px-4 py-3">
                  <span className="font-medium">{i.full_name}</span>
                  <span className="block text-xs text-slate-500">{i.email}</span>
                </td>
                <td className="px-4 py-3">{ROLE_LABEL[i.role]}</td>
                <td className="px-4 py-3">
                  <Badge tone={INVITATION_TONE[i.state]}>{INVITATION_LABEL[i.state]}</Badge>
                </td>
                <td className="px-4 py-3">{new Date(i.expires_at).toLocaleString()}</td>
                <td className="px-4 py-3">{i.invited_by_name ?? "—"}</td>
                <td className="space-x-1 whitespace-nowrap px-4 py-3">
                  {i.state !== "ACCEPTED" && i.state !== "REVOKED" && (
                    <Button variant="ghost" onClick={() => { setActionError(null); resend.mutate(i.id); }} aria-label={`Resend invitation to ${i.email}`}>
                      New link
                    </Button>
                  )}
                  {i.state === "PENDING" && (
                    <Button variant="danger-ghost" onClick={() => { setActionError(null); setRevoking(i); }} aria-label={`Revoke invitation for ${i.email}`}>
                      Revoke
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={inviting} title="Invite employee" onClose={() => setInviting(false)}>
        {inviting && (
          <InviteForm
            onClose={() => setInviting(false)}
            onCreated={async (invitation) => {
              setInviting(false);
              setCopied(false);
              setLink(invitation);
              await refresh();
              await queryClient.invalidateQueries({ queryKey: ["employees"] });
            }}
          />
        )}
      </Dialog>

      <Dialog open={link !== null} title="Invitation link" onClose={() => setLink(null)}>
        <div className="space-y-4">
          <Alert tone="warning">
            Copy this link now and send it to <strong>{link?.email}</strong> through a trusted channel. For security it is shown only once and expires {link ? new Date(link.expires_at).toLocaleString() : ""}.
          </Alert>
          <input readOnly aria-label="Invitation link" value={link?.invite_url ?? ""} onFocus={(e) => e.target.select()} className="block w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs" />
          <div className="flex items-center justify-end gap-3">
            {copied && <span role="status" className="text-sm text-green-700">Copied</span>}
            <Button variant="secondary" onClick={copy}>
              Copy link
            </Button>
            <Button onClick={() => setLink(null)}>Done</Button>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={revoking !== null}
        title="Revoke invitation"
        danger
        confirmLabel="Revoke"
        busy={revoke.isPending}
        error={actionError}
        message={<>Revoke the invitation for <strong>{revoking?.email}</strong>? Their link will stop working immediately.</>}
        onCancel={() => setRevoking(null)}
        onConfirm={() => revoking && revoke.mutate(revoking.id)}
      />
    </>
  );
}
