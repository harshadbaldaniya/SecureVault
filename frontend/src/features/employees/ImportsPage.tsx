import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { Alert, Badge, Button, Card, Dialog, EmptyState, PageHeader, PageLoader, Pagination, Table } from "@/components/ui";
import { api, ApiError, apiUrl, upload } from "@/services/api";
import type { ImportJob, Page } from "@/types/api";

const PAGE_SIZE = 25;
const STATUS_TONE = { QUEUED: "slate", PROCESSING: "blue", COMPLETED: "green", FAILED: "red" } as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function RowErrors({ job }: { job: ImportJob }) {
  if (job.file_error) return <Alert tone="error">{job.file_error}</Alert>;
  if (job.errors.length === 0) return <p className="text-sm text-slate-500">Every row was imported.</p>;
  return (
    <div className="max-h-[60vh] overflow-auto">
      <Table caption={`Rows that failed in ${job.file_name}`} headers={["Row", "Email", "Name", "Problem"]}>
        {job.errors.map((e) => (
          <tr key={e.row} className="align-top">
            <td className="px-4 py-2 tabular-nums">{e.row}</td>
            <td className="px-4 py-2">{e.email || "—"}</td>
            <td className="px-4 py-2">{e.full_name || "—"}</td>
            <td className="px-4 py-2">
              <ul className="space-y-1">
                {e.errors.map((problem, i) => (
                  <li key={i}>
                    {problem.field && <span className="font-mono text-xs text-slate-500">{problem.field}: </span>}
                    {problem.message}
                  </li>
                ))}
              </ul>
            </td>
          </tr>
        ))}
      </Table>
    </div>
  );
}

export function ImportsPage() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latest, setLatest] = useState<ImportJob | null>(null);
  const [details, setDetails] = useState<ImportJob | null>(null);
  const [page, setPage] = useState(1);

  const jobs = useQuery({
    queryKey: ["imports", page],
    queryFn: () => api.get<Page<ImportJob>>("/imports/", { page }),
    placeholderData: (p) => p,
    // Keep checking while a queued job is being processed by the worker.
    refetchInterval: (q) => (q.state.data?.results.some((j) => j.status === "QUEUED" || j.status === "PROCESSING") ? 3000 : false),
  });

  const send = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file as File);
      return upload<ImportJob>("/imports/", form);
    },
    onSuccess: async (job) => {
      setLatest(job);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
    onError: (e) => setError(message(e)),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.post<ImportJob>(`/imports/${id}/retry/`),
    onSuccess: async (job) => {
      setLatest(job);
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
    onError: (e) => setError(message(e)),
  });

  return (
    <>
      <PageHeader title="Employee import" description="Invite many employees at once from an Excel workbook. Each person receives a one-time activation link by email." />
      <div className="space-y-6">
        <Card title="Upload a workbook">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              if (!file) return setError("Choose an .xlsx file first.");
              if (!file.name.toLowerCase().endsWith(".xlsx")) return setError("Only .xlsx workbooks are accepted.");
              if (file.size > 2 * 1024 * 1024) return setError("The file is larger than 2 MB.");
              send.mutate();
            }}
          >
            {error && <Alert tone="error">{error}</Alert>}
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
              <li>
                Columns: <code>email</code>, <code>full_name</code>, optional <code>department</code> (code) and <code>role</code>.{" "}
                <a href={apiUrl("/imports/template/")} className="text-brand-700 underline">
                  Download the template
                </a>
              </li>
              <li>Everyone is invited as an Employee. Rows asking for an administrator role are refused; change roles after activation.</li>
              <li>Up to 2 MB and 5,000 rows. Larger files are processed in the background.</li>
            </ul>
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-sm">
                <span className="sr-only">Workbook</span>
                <input ref={fileInput} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" aria-label="Workbook to import" />
              </label>
              <Button type="submit" loading={send.isPending}>
                Upload and import
              </Button>
            </div>
          </form>
        </Card>

        {latest && (
          <Card title={`Result: ${latest.file_name}`}>
            {latest.status === "QUEUED" ? (
              <Alert tone="info">Queued: {latest.total_rows} rows will be processed in the background. This page updates automatically.</Alert>
            ) : latest.status === "FAILED" ? (
              <Alert tone="error">{latest.file_error}</Alert>
            ) : (
              <>
                <Alert tone={latest.failed_count ? "warning" : "success"}>
                  {latest.success_count} of {latest.total_rows} employees invited. {latest.failed_count ? `${latest.failed_count} rows need attention.` : ""}
                </Alert>
                {latest.failed_count > 0 && (
                  <div className="mt-4">
                    <RowErrors job={latest} />
                  </div>
                )}
              </>
            )}
          </Card>
        )}

        <Card title="Import history">
          {jobs.isPending ? (
            <PageLoader />
          ) : jobs.isError ? (
            <Alert tone="error">{message(jobs.error)}</Alert>
          ) : jobs.data.results.length === 0 ? (
            <EmptyState title="No imports yet" />
          ) : (
            <>
              <Table caption="Import history" headers={["File", "Uploaded", "Status", "Invited", "Failed", "Actions"]}>
                {jobs.data.results.map((job) => (
                  <tr key={job.id}>
                    <td className="px-4 py-3">
                      <span className="font-medium">{job.file_name}</span>
                      {job.retry_of && <span className="block text-xs text-slate-500">Retry of an earlier import</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {new Date(job.created_at).toLocaleString()}
                      <span className="block text-xs text-slate-500">{job.uploaded_by_name}</span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={STATUS_TONE[job.status]}>{job.status.toLowerCase()}</Badge>
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {job.success_count} / {job.total_rows}
                    </td>
                    <td className="px-4 py-3 tabular-nums">{job.failed_count}</td>
                    <td className="space-x-1 whitespace-nowrap px-4 py-3">
                      <Button variant="ghost" onClick={() => setDetails(job)} aria-label={`Details for ${job.file_name}`}>
                        Details
                      </Button>
                      {job.status === "COMPLETED" && job.failed_count > 0 && (
                        <Button variant="ghost" loading={retry.isPending && retry.variables === job.id} onClick={() => retry.mutate(job.id)} aria-label={`Retry failed rows of ${job.file_name}`}>
                          Retry failed rows
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </Table>
              <Pagination page={page} pageSize={PAGE_SIZE} count={jobs.data.count} onPage={setPage} />
            </>
          )}
        </Card>
      </div>
      <Dialog open={details !== null} title={details ? `Import details: ${details.file_name}` : ""} onClose={() => setDetails(null)}>
        {details && <RowErrors job={details} />}
        <div className="mt-4 flex justify-end">
          <Button variant="secondary" onClick={() => setDetails(null)}>
            Close
          </Button>
        </div>
      </Dialog>
    </>
  );
}
