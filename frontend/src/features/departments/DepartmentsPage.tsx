import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Department, Page } from "@/types/api";

const PAGE_SIZE = 25;
const schema = z.object({
  name: z.string().trim().min(1, "Enter a name.").max(120),
  code: z.string().trim().min(1, "Enter a code.").max(20),
  status: z.enum(["ACTIVE", "ARCHIVED"]),
});
type FormValues = z.infer<typeof schema>;

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function DepartmentForm({ department, onClose }: { department: Department | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: department?.name ?? "", code: department?.code ?? "", status: department?.status ?? "ACTIVE" },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) => (department ? api.patch(`/departments/${department.id}/`, values) : api.post("/departments/", values)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["departments"] });
      onClose();
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      let shown = false;
      for (const name of ["name", "code", "status"] as const) {
        if (fields[name]) {
          form.setError(name, { message: fields[name] });
          shown = true;
        }
      }
      if (!shown) setError(message(e));
    },
  });

  return (
    <form onSubmit={form.handleSubmit((values) => { setError(null); save.mutate(values); })} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <Field label="Name" error={form.formState.errors.name?.message}>
        {(props) => <Input {...props} {...form.register("name")} />}
      </Field>
      <Field label="Code" hint="Short unique code, e.g. ENG. Stored in upper case." error={form.formState.errors.code?.message}>
        {(props) => <Input {...props} {...form.register("code")} />}
      </Field>
      <Field label="Status" error={form.formState.errors.status?.message}>
        {(props) => (
          <Select {...props} {...form.register("status")}>
            <option value="ACTIVE">Active</option>
            <option value="ARCHIVED">Archived</option>
          </Select>
        )}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          {department ? "Save changes" : "Create department"}
        </Button>
      </div>
    </form>
  );
}

export function DepartmentsPage() {
  const { can } = useAuth();
  const canManage = can("departments.manage");
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Department | "new" | null>(null);
  const [deleting, setDeleting] = useState<Department | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["departments", page],
    queryFn: () => api.get<Page<Department>>("/departments/", { page }),
    placeholderData: (previous) => previous,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/departments/${id}/`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["departments"] });
      setDeleting(null);
    },
    onError: (e) => setDeleteError(message(e)),
  });

  return (
    <>
      <PageHeader
        title="Departments"
        description="Organizational units that group employees and bound access."
        actions={canManage && <Button onClick={() => setEditing("new")}>New department</Button>}
      />

      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{message(query.error)}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title="No departments yet" hint={canManage ? "Create the first department to organize employees." : undefined} />
      ) : (
        <>
          <Table caption="Departments" headers={canManage ? ["Name", "Code", "Head", "Employees", "Status", "Actions"] : ["Name", "Code", "Head", "Employees", "Status"]}>
            {query.data.results.map((d) => (
              <tr key={d.id}>
                <td className="px-4 py-3 font-medium">{d.name}</td>
                <td className="px-4 py-3 font-mono text-xs">{d.code}</td>
                <td className="px-4 py-3">{d.head_name ?? "—"}</td>
                <td className="px-4 py-3">{d.employee_count}</td>
                <td className="px-4 py-3">
                  <Badge tone={d.status === "ACTIVE" ? "green" : "slate"}>{d.status === "ACTIVE" ? "Active" : "Archived"}</Badge>
                </td>
                {canManage && (
                  <td className="space-x-2 px-4 py-3">
                    <Button variant="ghost" onClick={() => setEditing(d)} aria-label={`Edit ${d.name}`}>
                      Edit
                    </Button>
                    <Button variant="danger-ghost" onClick={() => { setDeleteError(null); setDeleting(d); }} aria-label={`Delete ${d.name}`}>
                      Delete
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
        </>
      )}

      <Dialog open={editing !== null} title={editing === "new" ? "New department" : "Edit department"} onClose={() => setEditing(null)}>
        {editing !== null && <DepartmentForm department={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete department"
        danger
        confirmLabel="Delete"
        busy={remove.isPending}
        error={deleteError}
        message={<>Delete <strong>{deleting?.name}</strong>? Departments that still have employees cannot be deleted; archive them instead.</>}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );
}
