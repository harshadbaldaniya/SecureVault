import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Field, Input, PageHeader, PageLoader, Pagination, Table, Textarea } from "@/components/ui";
import { useDebounced } from "@/hooks/useDebounced";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Page, SecureNote } from "@/types/api";

import { parseTags } from "./CredentialForm";
import { ClipboardNotice, SecretDialog } from "./SecretWidgets";
import { useSecretActions } from "./useSecretActions";

const PAGE_SIZE = 25;
const MAX_NOTE = 65_536;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function buildSchema(mode: "create" | "edit") {
  return z
    .object({
      title: z.string().trim().min(1, "Enter a title.").max(200),
      category: z.string().trim().max(40),
      tags: z.string(),
      content: z.string().max(MAX_NOTE, `Notes are limited to ${MAX_NOTE.toLocaleString()} characters.`),
    })
    .superRefine((values, ctx) => {
      if (mode === "create" && !values.content) ctx.addIssue({ code: "custom", path: ["content"], message: "Enter the note content." });
      if (parseTags(values.tags).length > 20) ctx.addIssue({ code: "custom", path: ["tags"], message: "Use at most 20 tags." });
    });
}
type FormValues = z.infer<ReturnType<typeof buildSchema>>;

function NoteForm({ note, onDone }: { note: SecureNote | null; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({
    resolver: zodResolver(buildSchema(note ? "edit" : "create")),
    defaultValues: { title: note?.title ?? "", category: note?.category ?? "", tags: note?.tags.join(", ") ?? "", content: "" },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const body: Record<string, unknown> = { title: values.title, category: values.category, tags: parseTags(values.tags) };
      if (values.content) body.content = values.content;
      return note ? api.patch(`/vault/notes/${note.id}/`, body) : api.post("/vault/notes/", body);
    },
    gcTime: 0,
    onSuccess: async () => {
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["notes"] });
      onDone();
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      const known = Object.keys(fields).filter((f) => f in form.getValues());
      if (known.length) known.forEach((f) => form.setError(f as keyof FormValues, { message: fields[f] ?? "Invalid value." }));
      else setError(message(e));
    },
  });

  const errors = form.formState.errors;
  return (
    <form onSubmit={form.handleSubmit((values) => { setError(null); save.mutate(values); })} noValidate className="space-y-4" autoComplete="off">
      {error && <Alert tone="error">{error}</Alert>}
      <Field label="Title" error={errors.title?.message}>
        {(props) => <Input {...props} {...form.register("title")} />}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Category" error={errors.category?.message}>
          {(props) => <Input {...props} {...form.register("category")} />}
        </Field>
        <Field label="Tags" hint="Comma-separated" error={errors.tags?.message}>
          {(props) => <Input {...props} {...form.register("tags")} />}
        </Field>
      </div>
      <Field label={note ? "New content (leave blank to keep the current note)" : "Content"} hint="Encrypted before it is stored. Never searchable." error={errors.content?.message}>
        {(props) => <Textarea {...props} spellCheck={false} {...form.register("content")} />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          {note ? "Save changes" : "Save note"}
        </Button>
      </div>
    </form>
  );
}

export function NotesPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [archived, setArchived] = useState(false);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search);
  const [editing, setEditing] = useState<SecureNote | "new" | null>(null);
  const [archiving, setArchiving] = useState<SecureNote | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const secrets = useSecretActions("notes", "content");

  const params = { page, archived: archived || undefined, search: debouncedSearch };
  const query = useQuery({
    queryKey: ["notes", params],
    queryFn: () => api.get<Page<SecureNote>>("/vault/notes/", params),
    placeholderData: (previous) => previous,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["notes"] });
  const archive = useMutation({
    mutationFn: (id: string) => api.delete(`/vault/notes/${id}/`),
    onSuccess: async () => {
      setArchiving(null);
      await invalidate();
    },
    onError: (e) => setActionError(message(e)),
  });
  const restore = useMutation({ mutationFn: (id: string) => api.post(`/vault/notes/${id}/restore/`), onSuccess: invalidate, onError: (e) => setActionError(message(e)) });
  const error = secrets.error ?? actionError;

  return (
    <>
      <PageHeader
        title="Secure notes"
        description="Encrypted notes for API keys, licence tokens and infrastructure configuration."
        actions={!archived && <Button onClick={() => setEditing("new")}>New note</Button>}
      />
      <ClipboardNotice state={secrets.clipboard} onDismiss={secrets.dismissClipboard} />
      {error && !archiving && (
        <Alert tone="error" className="mb-4">
          {error}
        </Alert>
      )}

      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="w-full sm:w-72">
          <Field label="Search" hint="Title and category only.">
            {(props) => <Input {...props} type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />}
          </Field>
        </div>
        <Button variant="secondary" onClick={() => { setArchived((a) => !a); setPage(1); }} aria-pressed={archived}>
          {archived ? "Show active notes" : "Show archived notes"}
        </Button>
      </div>

      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{message(query.error)}</Alert>
      ) : query.data.results.length === 0 ? (
        <EmptyState title={archived ? "No archived notes" : "No secure notes yet"} />
      ) : (
        <>
          <Table caption="Secure notes" headers={["Title", "Category", "Tags", "Updated", "Actions"]}>
            {query.data.results.map((n) => {
              const can = (p: string) => n.permissions.includes(p as never);
              const busy = secrets.busyId === n.id;
              return (
                <tr key={n.id}>
                  <td className="px-4 py-3 font-medium">{n.title}</td>
                  <td className="px-4 py-3">{n.category || "—"}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {n.tags.map((t) => (
                        <Badge key={t}>{t}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">{new Date(n.updated_at).toLocaleDateString()}</td>
                  <td className="space-x-1 whitespace-nowrap px-4 py-3">
                    {archived ? (
                      can("EDIT") && (
                        <Button variant="ghost" onClick={() => restore.mutate(n.id)} aria-label={`Restore ${n.title}`}>
                          Restore
                        </Button>
                      )
                    ) : (
                      <>
                        {can("REVEAL") && (
                          <Button variant="ghost" disabled={busy} onClick={() => void secrets.reveal(n.id, n.title)} aria-label={`Open ${n.title}`}>
                            Open
                          </Button>
                        )}
                        {can("COPY") && (
                          <Button variant="ghost" disabled={busy} onClick={() => void secrets.copy(n.id)} aria-label={`Copy ${n.title}`}>
                            Copy
                          </Button>
                        )}
                        {can("EDIT") && (
                          <Button variant="ghost" onClick={() => setEditing(n)} aria-label={`Edit ${n.title}`}>
                            Edit
                          </Button>
                        )}
                        {can("DELETE") && (
                          <Button variant="ghost" className="text-red-700" onClick={() => { setActionError(null); setArchiving(n); }} aria-label={`Archive ${n.title}`}>
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

      <Dialog open={editing !== null} title={editing === "new" ? "New secure note" : "Edit secure note"} onClose={() => setEditing(null)}>
        {editing !== null && <NoteForm note={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Dialog>
      <SecretDialog title={secrets.revealed?.title ?? ""} secret={secrets.revealed?.value ?? null} multiline onClose={secrets.closeReveal} />
      <ConfirmDialog
        open={archiving !== null}
        title="Archive note"
        danger
        confirmLabel="Archive"
        busy={archive.isPending}
        error={actionError}
        message={<>Archive <strong>{archiving?.title}</strong>? It can be restored for 30 days, then it is permanently deleted.</>}
        onCancel={() => setArchiving(null)}
        onConfirm={() => archiving && archive.mutate(archiving.id)}
      />
    </>
  );
}
