import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Alert, Button, FileInput, LinkButton, Segmented, TextLink } from "./ui";

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
