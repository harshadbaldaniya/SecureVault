import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, renderApp } from "@/tests/utils";
import type { ImportJob } from "@/types/api";

const page = <T,>(results: T[]) => ({ body: { count: results.length, next: null, previous: null, results } });
const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const FINISHED: ImportJob = {
  id: "j1",
  file_name: "people.xlsx",
  status: "COMPLETED",
  total_rows: 3,
  success_count: 2,
  failed_count: 1,
  errors: [
    {
      row: 4,
      email: "mallory@acme.test",
      full_name: "Mallory",
      department: "",
      role: "ORG_ADMIN",
      errors: [{ field: "role", message: "Administrator roles cannot be assigned by import. Change the role after the person activates." }],
    },
  ],
  file_error: "",
  uploaded_by_name: "Eve Example",
  retry_of: null,
  created_at: "2026-10-11T10:00:00Z",
  started_at: "2026-10-11T10:00:00Z",
  finished_at: "2026-10-11T10:00:01Z",
};

describe("employee import", () => {
  it("uploads the workbook as multipart form data and lists the rows that failed", async () => {
    const user = userEvent.setup();
    let jobs: ImportJob[] = [];
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("ORG_ADMIN") },
      "GET /imports/": () => page(jobs),
      "POST /imports/": () => {
        jobs = [FINISHED];
        return { status: 201, body: FINISHED };
      },
    });
    renderApp("/employees/import");
    await screen.findByText("No imports yet");

    const file = new File(["PK"], "people.xlsx", { type: XLSX_TYPE });
    await user.upload(screen.getByLabelText("Workbook to import"), file);
    await user.click(screen.getByRole("button", { name: "Upload and import" }));

    expect(await screen.findByText(/2 of 3 employees invited/)).toBeInTheDocument();
    const failed = screen.getByRole("table", { name: "Rows that failed in people.xlsx" });
    expect(within(failed).getByText(/Administrator roles cannot be assigned by import/)).toBeInTheDocument();

    const post = calls.find((c) => c.method === "POST" && c.path === "/imports/");
    expect(post?.body).toBeInstanceOf(FormData);
    expect(((post?.body as FormData).get("file") as File).name).toBe("people.xlsx");
    // The browser must set the multipart boundary itself; a hand-written Content-Type would break the upload.
    expect(post?.headers["Content-Type"]).toBeUndefined();
    expect(post?.headers).toHaveProperty("X-CSRFToken");

    // History refreshes after the upload.
    expect(await screen.findByRole("table", { name: "Import history" })).toBeInTheDocument();
  });

  it("refuses a file that is not an .xlsx workbook without uploading it", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { calls } = mockFetch({ "GET /auth/me/": { body: makeMe("ORG_ADMIN") }, "GET /imports/": page([]) });
    renderApp("/employees/import");
    await screen.findByText("No imports yet");

    await user.upload(screen.getByLabelText("Workbook to import"), new File(["a,b"], "people.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Upload and import" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Only .xlsx workbooks are accepted.");
    expect(calls.some((c) => c.method === "POST" && c.path === "/imports/")).toBe(false);
  });

  it("shows the server's reason when a workbook is rejected", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /auth/me/": { body: makeMe("ORG_ADMIN") },
      "GET /imports/": page([]),
      "POST /imports/": { status: 400, body: { error: { code: "invalid_file", message: "The file is not a valid .xlsx workbook." } } },
    });
    renderApp("/employees/import");
    await screen.findByText("No imports yet");

    await user.upload(screen.getByLabelText("Workbook to import"), new File(["not a zip"], "people.xlsx", { type: XLSX_TYPE }));
    await user.click(screen.getByRole("button", { name: "Upload and import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is not a valid .xlsx workbook.");
  });

  it("shows the details of a past import and retries only its failed rows", async () => {
    const user = userEvent.setup();
    const retried: ImportJob = { ...FINISHED, id: "j2", retry_of: "j1", total_rows: 1, success_count: 1, failed_count: 0, errors: [] };
    const { calls } = mockFetch({
      "GET /auth/me/": { body: makeMe("ORG_ADMIN") },
      "GET /imports/": page([FINISHED]),
      "POST /imports/j1/retry/": { status: 201, body: retried },
    });
    renderApp("/employees/import");

    await user.click(await screen.findByRole("button", { name: "Details for people.xlsx" }));
    const dialog = screen.getByRole("dialog", { name: "Import details: people.xlsx" });
    expect(within(dialog).getByText("mallory@acme.test")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByText("mallory@acme.test")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry failed rows of people.xlsx" }));
    expect(await screen.findByText(/1 of 1 employees invited/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST" && c.path === "/imports/j1/retry/")).toHaveLength(1);
  });

  it.each(["EMPLOYEE", "SEC_ADMIN"] as const)("is not available to %s", async (role) => {
    const { calls } = mockFetch({ "GET /auth/me/": { body: makeMe(role) } });
    renderApp("/employees/import");
    expect(await screen.findByRole("heading", { name: "You do not have access to this page" })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/imports/")).toBe(false);
  });
});
