import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";

import { EmployeeDirectory } from "./EmployeeDirectory";
import { InvitationsPanel } from "./InvitationsPanel";

export function EmployeesPage() {
  const { can } = useAuth();
  const canInvite = can("invitations.manage");
  const [tab, setTab] = useState<"employees" | "invitations">("employees");

  return (
    <>
      <PageHeader
        title="Employees"
        description="People in your organization. New employees join through single-use invitations."
        actions={
          canInvite && (
            <Link to="/employees/import" className="inline-flex min-h-10 items-center rounded-md bg-white px-4 text-sm font-medium text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50">
              Import from Excel
            </Link>
          )
        }
      />
      {canInvite && (
        <div role="tablist" aria-label="Employee views" className="mb-4 flex gap-1 border-b border-slate-200">
          {(["employees", "invitations"] as const).map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              id={`tab-${name}`}
              aria-selected={tab === name}
              aria-controls={`panel-${name}`}
              onClick={() => setTab(name)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === name ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
            >
              {name === "employees" ? "Directory" : "Invitations"}
            </button>
          ))}
        </div>
      )}
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "employees" || !canInvite ? <EmployeeDirectory /> : <InvitationsPanel />}
      </div>
    </>
  );
}
