import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Field, Input, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { useDebounced } from "@/hooks/useDebounced";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Employee, Page, Role, UserStatus } from "@/types/api";

import { ROLE_LABEL, STATUS_LABEL, STATUS_TONE } from "./labels";
import { useDepartmentOptions } from "./useDepartmentOptions";

const PAGE_SIZE = 25;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

const editSchema = z.object({
  full_name: z.string().trim().min(1, "Enter a name.").max(150),
  role: z.enum(["ORG_ADMIN", "SEC_ADMIN", "EMPLOYEE"]),
  status: z.enum(["ACTIVE", "SUSPENDED", "DEACTIVATED", "INVITED"]),
  department: z.string(),
});
type EditValues = z.infer<typeof editSchema>;

function EditEmployee({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const queryClient = useQueryClient();
  const departments = useDepartmentOptions();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { full_name: employee.full_name, role: employee.role, status: employee.status, department: employee.department ?? "" },
  });

  const save = useMutation({
    mutationFn: (values: EditValues) => {
      // Send only what changed; the server re-validates every rule (self-change, last admin, status flow).
      const body: Record<string, unknown> = {};
      if (values.full_name !== employee.full_name) body.full_name = values.full_name;
      if (values.role !== employee.role) body.role = values.role;
      if (values.status !== employee.status) body.status = values.status;
      if (values.department !== (employee.department ?? "")) body.department = values.department || null;
      return api.patch(`/users/${employee.id}/`, body);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
      onClose();
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      const names = Object.keys(fields);
      if (names.length) names.forEach((n) => form.setError(n as keyof EditValues, { message: fields[n] ?? "Invalid value." }));
      else setError(message(e));
    },
  });

  const invited = employee.status === "INVITED";

  return (
    <form onSubmit={form.handleSubmit((values) => { setError(null); save.mutate(values); })} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <p className="text-sm text-slate-500">{employee.email}</p>
      <Field label="Full name" error={form.formState.errors.full_name?.message}>
        {(props) => <Input {...props} {...form.register("full_name")} />}
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
      <Field label="Status" hint={invited ? "Invited users activate through their invitation link." : undefined} error={form.formState.errors.status?.message}>
        {(props) => (
          <Select {...props} {...form.register("status")}>
            {invited && <option value="INVITED">Invited</option>}
            <option value="ACTIVE" disabled={invited}>Active</option>
            <option value="SUSPENDED" disabled={invited}>Suspended</option>
            <option value="DEACTIVATED">Deactivated</option>
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
      <p className="text-xs text-slate-500">Suspending or deactivating an employee signs them out everywhere immediately.</p>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          Save changes
        </Button>
      </div>
    </form>
  );
}

type Action = { kind: "reset-mfa" | "reset-link"; employee: Employee };

export function EmployeeDirectory() {
  const { user, can } = useAuth();
  const canManage = can("users.manage");
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const debouncedSearch = useDebounced(search);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [resetUrl, setResetUrl] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["employees", page, debouncedSearch, role, status],
    queryFn: () => api.get<Page<Employee>>("/users/", { page, search: debouncedSearch, role, status }),
    placeholderData: (previous) => previous,
  });

  const run = useMutation({
    mutationFn: async (a: Action) => {
      if (a.kind === "reset-mfa") {
        await api.post(`/users/${a.employee.id}/reset-mfa/`);
        return null;
      }
      return (await api.post<{ reset_url: string }>(`/users/${a.employee.id}/password-reset-link/`)).reset_url;
    },
    onSuccess: async (url, a) => {
      await queryClient.invalidateQueries({ queryKey: ["employees"] });
      setAction(null);
      if (a.kind === "reset-link") setResetUrl(url);
    },
    onError: (e) => setActionError(message(e)),
  });

  const filter = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1); };

  return (
    <>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Field label="Search">{(props) => <Input {...props} type="search" value={search} onChange={(e) => filter(setSearch)(e.target.value)} placeholder="Name or email" />}</Field>
        <Field label="Role">
          {(props) => (
            <Select {...props} value={role} onChange={(e) => filter(setRole)(e.target.value)}>
              <option value="">All roles</option>
              {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Status">
          {(props) => (
            <Select {...props} value={status} onChange={(e) => filter(setStatus)(e.target.value)}>
              <option value="">All statuses</option>
              {(Object.keys(STATUS_LABEL) as UserStatus[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{message(query.error)}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title="No employees match" hint="Try different filters." />
      ) : (
        <>
          <Table caption="Employees" headers={canManage ? ["Name", "Role", "Department", "Status", "Last sign-in", "Actions"] : ["Name", "Role", "Department", "Status", "Last sign-in"]}>
            {query.data.results.map((e) => (
              <tr key={e.id}>
                <td className="px-4 py-3">
                  <span className="font-medium">{e.full_name}</span>
                  <span className="block text-xs text-slate-500">{e.email}</span>
                </td>
                <td className="px-4 py-3">{ROLE_LABEL[e.role]}</td>
                <td className="px-4 py-3">{e.department_name ?? "—"}</td>
                <td className="px-4 py-3">
                  <Badge tone={STATUS_TONE[e.status]}>{STATUS_LABEL[e.status]}</Badge>
                </td>
                <td className="px-4 py-3">{e.last_login ? new Date(e.last_login).toLocaleString() : "Never"}</td>
                {canManage && (
                  <td className="space-x-1 whitespace-nowrap px-4 py-3">
                    {e.id === user?.id ? (
                      <span className="text-xs text-slate-400">You</span>
                    ) : (
                      <>
                        <Button variant="ghost" onClick={() => setEditing(e)} aria-label={`Edit ${e.full_name}`}>
                          Edit
                        </Button>
                        {e.status === "ACTIVE" && (
                          <>
                            <Button variant="ghost" onClick={() => { setActionError(null); setAction({ kind: "reset-link", employee: e }); }} aria-label={`Create password reset link for ${e.full_name}`}>
                              Reset link
                            </Button>
                            <Button variant="ghost" onClick={() => { setActionError(null); setAction({ kind: "reset-mfa", employee: e }); }} aria-label={`Reset two-step verification for ${e.full_name}`}>
                              Reset MFA
                            </Button>
                          </>
                        )}
                      </>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={editing !== null} title="Edit employee" onClose={() => setEditing(null)}>
        {editing && <EditEmployee employee={editing} onClose={() => setEditing(null)} />}
      </Dialog>

      <ConfirmDialog
        open={action !== null}
        title={action?.kind === "reset-mfa" ? "Reset two-step verification" : "Create password reset link"}
        danger={action?.kind === "reset-mfa"}
        confirmLabel={action?.kind === "reset-mfa" ? "Reset MFA" : "Create link"}
        busy={run.isPending}
        error={actionError}
        message={
          action?.kind === "reset-mfa" ? (
            <>Remove two-step verification for <strong>{action.employee.full_name}</strong> and sign them out everywhere? Only do this after confirming their identity.</>
          ) : (
            <>Create a one-time password reset link for <strong>{action?.employee.full_name}</strong>? Share it with them through a trusted channel. It expires in 30 minutes.</>
          )
        }
        onCancel={() => setAction(null)}
        onConfirm={() => action && run.mutate(action)}
      />

      <Dialog open={resetUrl !== null} title="Password reset link" onClose={() => setResetUrl(null)}>
        <div className="space-y-4">
          <Alert tone="warning">This link is shown once and grants the right to set a new password. Share it only with the employee.</Alert>
          <input readOnly aria-label="Password reset link" value={resetUrl ?? ""} onFocus={(e) => e.target.select()} className="block w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs" />
          <div className="flex justify-end">
            <Button onClick={() => setResetUrl(null)}>Done</Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
