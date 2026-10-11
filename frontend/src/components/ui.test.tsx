import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Alert, Button, ConfirmDialog, Dialog, FileInput, LinkButton, Pagination, Segmented, Table, TextLink } from "./ui";

describe("action components", () => {
  it("renders navigation as a link that looks like a button, and downloads as a plain anchor", () => {
    render(
      <MemoryRouter>
        <LinkButton to="/audit">Open the audit log</LinkButton>
        <LinkButton href="/api/v1/imports/template/" download>
          Download the template
        </LinkButton>
        <TextLink to="/vault">Open the vault</TextLink>
      </MemoryRouter>,
    );
    const internal = screen.getByRole("link", { name: "Open the audit log" });
    expect(internal).toHaveAttribute("href", "/audit");
    expect(internal.className).toContain("ring-1"); // secondary button treatment
    const download = screen.getByRole("link", { name: "Download the template" });
    expect(download).toHaveAttribute("href", "/api/v1/imports/template/");
    expect(download).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Open the vault" }).className).not.toContain("ring-1"); // stays lightweight
  });

  it("uses one consistent treatment per role: primary, secondary, ghost and destructive", () => {
    render(
      <>
        <Button>Save</Button>
        <Button variant="secondary">Cancel</Button>
        <Button variant="ghost">Edit</Button>
        <Button variant="danger-ghost">Revoke</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Save" }).className).toContain("bg-brand-600");
    expect(screen.getByRole("button", { name: "Cancel" }).className).toContain("ring-slate-300");
    expect(screen.getByRole("button", { name: "Edit" }).className).toContain("hover:bg-slate-100");
    expect(screen.getByRole("button", { name: "Revoke" }).className).toContain("text-red-700");
  });

  it("shows a loading button as busy and not clickable", async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Upload and import
      </Button>,
    );
    const button = screen.getByRole("button", { name: /Upload and import/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("segmented control marks the selected view, switches on click and works from the keyboard", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [view, setView] = useState<"chart" | "table">("chart");
      return (
        <Segmented
          label="Activity view"
          value={view}
          options={[
            { value: "chart", label: "Chart" },
            { value: "table", label: "Table" },
          ]}
          onChange={setView}
        />
      );
    }
    render(<Harness />);
    const group = screen.getByRole("group", { name: "Activity view" });
    const chart = within(group).getByRole("button", { name: "Chart" });
    const table = within(group).getByRole("button", { name: "Table" });
    expect(chart).toHaveAttribute("aria-pressed", "true");
    expect(table).toHaveAttribute("aria-pressed", "false");

    await user.tab(); // first option
    expect(chart).toHaveFocus();
    await user.tab();
    expect(table).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(table).toHaveAttribute("aria-pressed", "true");
    expect(chart).toHaveAttribute("aria-pressed", "false");
  });

  it("file input: a visible button, a readable file name, and the native input stays keyboard-focusable", async () => {
    const user = userEvent.setup();
    const picked: Array<string | null> = [];
    function Harness() {
      const [file, setFile] = useState<File | null>(null);
      return (
        <FileInput
          accept=".xlsx"
          fileName={file?.name ?? null}
          onFile={(f) => {
            picked.push(f?.name ?? null);
            setFile(f);
          }}
        />
      );
    }
    render(<Harness />);
    expect(screen.getByText("No file selected")).toBeInTheDocument();
    const input = screen.getByLabelText("Choose file");
    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveAttribute("accept", ".xlsx");

    await user.tab();
    expect(input).toHaveFocus(); // reachable with the keyboard even though it is visually replaced by the button

    await user.upload(input, new File(["x"], "people.xlsx"));
    expect(screen.getByText("people.xlsx")).toBeInTheDocument();
    expect(picked).toEqual(["people.xlsx"]);
  });

  it("alert action sits inside the notice and the message stays a status, not a button", () => {
    render(
      <MemoryRouter>
        <Alert tone="info" action={<LinkButton to="/security">Turn it on</LinkButton>}>
          Two-step verification is off for your account.
        </Alert>
      </MemoryRouter>,
    );
    const notice = screen.getByRole("status");
    expect(within(notice).getByText("Two-step verification is off for your account.")).toBeInTheDocument();
    expect(within(notice).getByRole("link", { name: "Turn it on" })).toHaveAttribute("href", "/security");
  });
});

describe("table and pagination", () => {
  it("makes an overflowing table a labelled, keyboard-focusable region and leaves short tables alone", () => {
    const scroll = vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(900);
    const client = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(300);
    const { unmount } = render(
      <Table caption="Employees" headers={["Name"]}>
        <tr>
          <td>Eve</td>
        </tr>
      </Table>,
    );
    expect(screen.getByRole("region", { name: "Employees (scrollable)" })).toHaveAttribute("tabindex", "0");
    unmount();
    scroll.mockRestore();
    client.mockRestore();

    render(
      <Table caption="Short" headers={["Name"]}>
        <tr>
          <td>Eve</td>
        </tr>
      </Table>,
    );
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("only offers Previous and Next when there is more than one page", () => {
    const { rerender } = render(<Pagination page={1} pageSize={25} count={3} onPage={() => {}} />);
    expect(screen.getByText("Page 1 of 1 · 3 total")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    rerender(<Pagination page={1} pageSize={25} count={60} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });
});

describe("dialogs", () => {
  function Harness({ onSubmit = () => {} }: { onSubmit?: () => void }) {
    const [open, setOpen] = useState(true);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open it
        </button>
        <Dialog open={open} title="Edit thing" onClose={() => setOpen(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit();
            }}
          >
            <label>
              Name
              <input name="name" />
            </label>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </form>
        </Dialog>
      </>
    );
  }

  it("has an accessible × that closes a clean dialog without submitting anything", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const dialog = screen.getByRole("dialog", { name: "Edit thing" });
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("dialog", { name: "Edit thing" })).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("asks before throwing away typed input, and Keep editing returns to the form with the text intact", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const dialog = screen.getByRole("dialog", { name: "Edit thing" });
    await user.type(within(dialog).getByLabelText("Name"), "draft");
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Discard your unsaved changes?");
    expect(within(dialog).getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    expect(within(dialog).getByLabelText("Name")).toHaveValue("draft");
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    await user.click(within(dialog).getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("dialog", { name: "Edit thing" })).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("typing and then reverting is not a change: no discard prompt", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const dialog = screen.getByRole("dialog", { name: "Edit thing" });
    const name = within(dialog).getByLabelText("Name");
    await user.type(name, "abc");
    await user.clear(name);
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("dialog", { name: "Edit thing" })).not.toBeInTheDocument();
  });

  it("a field changed by a button (no typing) still counts as unsaved", async () => {
    const user = userEvent.setup();
    function Generator() {
      const [value, setValue] = useState("");
      return (
        <Dialog open title="Make one" onClose={() => {}}>
          <form>
            <input aria-label="Secret" value={value} readOnly />
            <button type="button" onClick={() => setValue("generated")}>
              Generate
            </button>
          </form>
        </Dialog>
      );
    }
    render(<Generator />);
    const dialog = screen.getByRole("dialog", { name: "Make one" });
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Discard your unsaved changes?");
  });

  it("an explicit Cancel closes at once and never submits the form", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const dialog = screen.getByRole("dialog", { name: "Edit thing" });
    await user.type(within(dialog).getByLabelText("Name"), "x");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Edit thing" })).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("a confirmation question offers Cancel and the action, without a second close control", () => {
    render(<ConfirmDialog open title="Archive it?" message="Sure?" confirmLabel="Archive" danger onConfirm={() => {}} onCancel={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: "Archive it?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Archive" }).className).toContain("bg-red-600");
    expect(within(dialog).queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument();
  });
});

describe("contrast of text on tinted notices", () => {
  // Tailwind palette values used by the active-lockdown card: slate-700 text on red-50.
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  };
  const ratio = (a: string, b: string) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi! + 0.05) / (lo! + 0.05);
  };
  it("the lockdown card's detail text passes WCAG AA (4.5:1); the old slate-500 did not", () => {
    expect(ratio("#314158", "#fef2f2")).toBeGreaterThanOrEqual(4.5); // slate-700 on red-50
    expect(ratio("#62748e", "#fef2f2")).toBeLessThan(4.5); // slate-500 on red-50 (what it used to be)
  });
});

describe("table focus", () => {
  it("shows focus on the header row, not as an outline around the whole (possibly very tall) region", () => {
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(900);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(300);
    render(
      <Table caption="Audit log" headers={["Time"]}>
        <tr>
          <td>now</td>
        </tr>
      </Table>,
    );
    const region = screen.getByRole("region", { name: "Audit log (scrollable)" });
    expect(region.className).toContain("focus-visible:outline-none");
    expect(region.className).toContain("[&:focus-visible_thead_th]");
    vi.restoreAllMocks();
  });
});
