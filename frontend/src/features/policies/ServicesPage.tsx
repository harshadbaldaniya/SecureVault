import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Select, Table, TextLink } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { useDebounced } from "@/hooks/useDebounced";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Page, ServiceCategory, ServiceItem } from "@/types/api";

const PAGE_SIZE = 25;
const CATEGORIES: Array<[ServiceCategory, string]> = [
  ["CLOUD", "Cloud infrastructure"],
  ["DATABASE", "Database"],
  ["DEVOPS", "DevOps / CI"],
  ["SAAS", "SaaS application"],
  ["INTERNAL", "Internal service"],
  ["OTHER", "Other"],
];
const categoryLabel = Object.fromEntries(CATEGORIES) as Record<ServiceCategory, string>;

const webUrl = z
  .string()
  .trim()
  .refine((v) => v === "" || /^https?:\/\/\S+$/i.test(v), "Use a full http:// or https:// address.");

const schema = z.object({
  name: z.string().trim().min(1, "Enter a name.").max(120),
  category: z.enum(["CLOUD", "DATABASE", "DEVOPS", "SAAS", "INTERNAL", "OTHER"]),
  base_url: webUrl,
  icon_url: webUrl,
  default_port: z
    .string()
    .trim()
    .refine((v) => v === "" || (/^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 65535), "Enter a port between 1 and 65535."),
  status: z.enum(["ACTIVE", "INACTIVE"]),
});
type FormValues = z.infer<typeof schema>;

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function ServiceForm({ service, onClose }: { service: ServiceItem | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: service?.name ?? "",
      category: service?.category ?? "OTHER",
      base_url: service?.base_url ?? "",
      icon_url: service?.icon_url ?? "",
      default_port: service?.default_port?.toString() ?? "",
      status: service?.status ?? "ACTIVE",
    },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const body = { ...values, default_port: values.default_port === "" ? null : Number(values.default_port) };
      return service ? api.patch(`/services/${service.id}/`, body) : api.post("/services/", body);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["services"] });
      onClose();
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      let shown = false;
      for (const name of ["name", "category", "base_url", "icon_url", "default_port", "status"] as const) {
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
      <Field label="Category" error={form.formState.errors.category?.message}>
        {(props) => (
          <Select {...props} {...form.register("category")}>
            {CATEGORIES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Base URL" hint="Optional. Shown as a link; SecureVault never contacts it." error={form.formState.errors.base_url?.message}>
        {(props) => <Input {...props} type="url" inputMode="url" {...form.register("base_url")} />}
      </Field>
      <Field label="Icon URL" error={form.formState.errors.icon_url?.message}>
        {(props) => <Input {...props} type="url" inputMode="url" {...form.register("icon_url")} />}
      </Field>
      <Field label="Default port" error={form.formState.errors.default_port?.message}>
        {(props) => <Input {...props} inputMode="numeric" {...form.register("default_port")} />}
      </Field>
      <Field label="Status" error={form.formState.errors.status?.message}>
        {(props) => (
          <Select {...props} {...form.register("status")}>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </Select>
        )}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          {service ? "Save changes" : "Add service"}
        </Button>
      </div>
    </form>
  );
}

export function ServicesPage() {
  const { can } = useAuth();
  const canManage = can("services.manage");
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const debouncedSearch = useDebounced(search);
  const [editing, setEditing] = useState<ServiceItem | "new" | null>(null);
  const [deleting, setDeleting] = useState<ServiceItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["services", page, debouncedSearch, category],
    queryFn: () => api.get<Page<ServiceItem>>("/services/", { page, search: debouncedSearch, category }),
    placeholderData: (previous) => previous,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/services/${id}/`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["services"] });
      setDeleting(null);
    },
    onError: (e) => setDeleteError(message(e)),
  });

  return (
    <>
      <PageHeader
        title="Service catalog"
        description="The tools and internal services that credentials belong to."
        actions={canManage && <Button onClick={() => setEditing("new")}>Add service</Button>}
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-full sm:w-64">
          <Field label="Search">{(props) => <Input {...props} type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Name" />}</Field>
        </div>
        <div className="w-full sm:w-56">
          <Field label="Category">
            {(props) => (
              <Select {...props} value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
                <option value="">All categories</option>
                {CATEGORIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
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
        <EmptyState title="No services found" hint={canManage ? "Add the tools your teams store credentials for." : undefined} />
      ) : (
        <>
          <Table caption="Service catalog" headers={canManage ? ["Name", "Category", "Address", "Port", "Status", "Actions"] : ["Name", "Category", "Address", "Port", "Status"]}>
            {query.data.results.map((s) => (
              <tr key={s.id}>
                <td className="px-4 py-3 font-medium">{s.name}</td>
                <td className="px-4 py-3">{categoryLabel[s.category]}</td>
                <td className="px-4 py-3">
                  {s.base_url ? (
                    <TextLink href={s.base_url} target="_blank" rel="noopener noreferrer" className="font-normal">
                      {s.base_url}
                    </TextLink>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-3">{s.default_port ?? "—"}</td>
                <td className="px-4 py-3">
                  <Badge tone={s.status === "ACTIVE" ? "green" : "slate"}>{s.status === "ACTIVE" ? "Active" : "Inactive"}</Badge>
                </td>
                {canManage && (
                  <td className="space-x-2 px-4 py-3">
                    <Button variant="ghost" onClick={() => setEditing(s)} aria-label={`Edit ${s.name}`}>
                      Edit
                    </Button>
                    <Button variant="danger-ghost" onClick={() => { setDeleteError(null); setDeleting(s); }} aria-label={`Delete ${s.name}`}>
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

      <Dialog open={editing !== null} title={editing === "new" ? "Add service" : "Edit service"} onClose={() => setEditing(null)}>
        {editing !== null && <ServiceForm service={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete service"
        danger
        confirmLabel="Delete"
        busy={remove.isPending}
        error={deleteError}
        message={<>Delete <strong>{deleting?.name}</strong> from the catalog?</>}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );
}
